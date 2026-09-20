"""Dedicated input thread. Callbacks do no disk I/O or synchronous cross-process messaging."""

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import threading

from . import win32 as w
from .window_manager import candidate_at, window_class
from .input_mask import mask_alt_menu, MENU_MASK_MARKER
from .shortcuts import ShortcutMatcher, MODIFIERS


@dataclass
class Gesture:
    serial: int
    hwnd: int
    origin: tuple[int, int]
    started: bool = False
    kind: str = "move"


class Hooks(threading.Thread):
    def __init__(self, control_hwnd, commands, test_input=False, shortcuts=None):
        super().__init__(name="InputHook", daemon=True)
        self.control_hwnd, self.commands = control_hwnd, commands
        self.test_input = test_input
        self.shortcuts = ShortcutMatcher(shortcuts or {})
        self.shortcut_mask = False
        self.ready = threading.Event()
        self.error = None
        self.tid = None
        self.gesture = None
        self.serial = 0
        self.eat_left_up = False
        self.eat_right_up = False
        self.eat_escape_up = False
        self.latest_position = None
        self.motion_pending = False
        # This belongs to the entire Alt press, not the lifetime of a mouse gesture.
        self.mask_alt_on_release = False
        self.alt_keys_down = set()
        self.drag_x = max(4, w.GetSystemMetrics(68))
        self.drag_y = max(4, w.GetSystemMetrics(69))
        # Keep callbacks alive until both hooks are unregistered.
        self.mouse_callback = w.HOOKPROC(self._mouse)
        self.keyboard_callback = w.HOOKPROC(self._keyboard)

    def submit(self, kind, *args):
        self.commands.put((kind, *args))
        w.check(w.PostMessage(self.control_hwnd, w.WM_APP_ACTION, 0, 0), "PostMessage(controller)")

    def reset(self, serial):
        if self.tid:
            w.PostThreadMessage(self.tid, w.WM_APP_RESET, serial, 0)

    def stop(self):
        if self.tid:
            w.PostThreadMessage(self.tid, w.WM_QUIT, 0, 0)

    def _fail(self, error):
        self.error = error
        self.gesture = None
        # Defer traceback/logging and cleanup to the controller.
        self.commands.put(("hook_error", repr(error)))
        w.PostMessage(self.control_hwnd, w.WM_APP_ACTION, 0, 0)
        w.PostQuitMessage(1)

    def _accept(self, flags, marker, injected_mask):
        if self.test_input:
            return bool(flags & injected_mask and marker == w.TEST_INPUT_MARKER)
        return not flags & injected_mask

    def _mouse(self, code, message, pointer):
        if code < 0:
            return w.CallNextHookEx(None, code, message, pointer)
        try:
            event = C.cast(pointer, C.POINTER(w.MSLLHOOKSTRUCT)).contents
            if not self._accept(event.flags, event.dwExtraInfo, 1):
                return w.CallNextHookEx(None, code, message, pointer)
            if message in (w.WM_LBUTTONDOWN, w.WM_RBUTTONDOWN):
                kind = "move" if message == w.WM_LBUTTONDOWN else "resize"
                eat_attribute = "eat_left_up" if kind == "move" else "eat_right_up"
                if self.gesture:
                    # A second button cannot open a menu or switch the active gesture.
                    setattr(self, eat_attribute, True)
                    return 1
                can_start = not (self.eat_left_up or self.eat_right_up) and w.key_down(w.VK_MENU)
                # Avoid AltGr and other modified mouse shortcuts.
                if can_start and not any(w.key_down(vk) for vk in (0x11, 0x10, 0x5B, 0x5C)):
                    hwnd = candidate_at(event.pt.x, event.pt.y, resizing=kind == "resize")
                    if hwnd and self.test_input and window_class(hwnd) != "WindowGlide.AutomationFixture":
                        hwnd = None
                    if hwnd:
                        self.serial += 1
                        self.gesture = Gesture(self.serial, hwnd, (event.pt.x, event.pt.y), kind=kind)
                        if kind == "resize":
                            # Includes the inactive center: a consumed right click
                            # must not turn into a bare-Alt menu activation later.
                            self.mask_alt_on_release = True
                        self.latest_position = (self.serial, self.gesture.origin)
                        setattr(self, eat_attribute, True)
                        self.submit("armed", self.serial, hwnd, self.gesture.origin, kind)
                        return 1
            elif message == w.WM_MOUSEMOVE and self.gesture:
                g = self.gesture
                self.latest_position = (g.serial, (event.pt.x, event.pt.y))
                if not g.started and (abs(event.pt.x - g.origin[0]) >= self.drag_x or abs(event.pt.y - g.origin[1]) >= self.drag_y):
                    g.started = True
                    self.mask_alt_on_release = True
                    self.submit("start", g.serial, (event.pt.x, event.pt.y))
                elif g.started and not self.motion_pending:
                    self.motion_pending = True
                    self.submit("motion", g.serial)
            elif message in (w.WM_LBUTTONUP, w.WM_RBUTTONUP):
                kind = "move" if message == w.WM_LBUTTONUP else "resize"
                eat_attribute = "eat_left_up" if kind == "move" else "eat_right_up"
                if not getattr(self, eat_attribute):
                    return w.CallNextHookEx(None, code, message, pointer)
                setattr(self, eat_attribute, False)
                if self.gesture and self.gesture.kind == kind:
                    point = (event.pt.x, event.pt.y)
                    self.latest_position = (self.gesture.serial, point)
                    self.submit("finish", self.gesture.serial, "mouse released", point)
                    self.gesture = None
                return 1
        except Exception as exc:
            self._fail(exc)
        return w.CallNextHookEx(None, code, message, pointer)

    def _keyboard(self, code, message, pointer):
        if code < 0:
            return w.CallNextHookEx(None, code, message, pointer)
        try:
            event = C.cast(pointer, C.POINTER(w.KBDLLHOOKSTRUCT)).contents
            up = message in (w.WM_KEYUP, w.WM_SYSKEYUP)
            # Touchpad custom shortcuts may be injected. Accept them ONLY for
            # chord matching, never as synthetic Alt+mouse gestures. Our own
            # neutral menu-mask events must never feed back into the matcher.
            shortcut_input = event.dwExtraInfo != MENU_MASK_MARKER and (
                not self.test_input or self._accept(event.flags, event.dwExtraInfo, 0x10))
            if shortcut_input and self.shortcuts.bindings:
                consumed, action = self.shortcuts.feed(event.vkCode, up)
                if action:
                    self.shortcut_mask = True
                    if not mask_alt_menu():
                        self.submit("mask_failed", C.get_last_error())
                    self.submit("shortcut", action, w.GetForegroundWindow())
                if up and self.shortcut_mask and MODIFIERS.get(event.vkCode) in ("Alt", "Win"):
                    if not mask_alt_menu():
                        self.submit("mask_failed", C.get_last_error())
                if not any(key in MODIFIERS for key in self.shortcuts.down):
                    self.shortcut_mask = False
                if consumed:
                    return 1
            if not self._accept(event.flags, event.dwExtraInfo, 0x10):
                return w.CallNextHookEx(None, code, message, pointer)
            is_alt = event.vkCode in (w.VK_MENU, w.VK_LMENU, w.VK_RMENU)
            if is_alt and not up:
                if not self.alt_keys_down:
                    self.mask_alt_on_release = False
                self.alt_keys_down.add(event.vkCode)
            if event.vkCode == w.VK_ESCAPE:
                if up and self.eat_escape_up:
                    self.eat_escape_up = False
                    return 1
                if not up and (self.gesture or self.eat_escape_up):
                    self.eat_escape_up = True
                    if self.gesture:
                        self.submit("finish", self.gesture.serial, "escape (keep result)", self.latest_position[1])
                        self.gesture = None
                    return 1
            if up and is_alt:
                if self.gesture:
                    self.submit("finish", self.gesture.serial, "alt released", self.latest_position[1])
                    self.gesture = None
                if self.mask_alt_on_release and not mask_alt_menu():
                    self.submit("mask_failed", C.get_last_error())
                self.alt_keys_down.discard(event.vkCode)
                if not self.alt_keys_down:
                    self.mask_alt_on_release = False
        except Exception as exc:
            self._fail(exc)
        return w.CallNextHookEx(None, code, message, pointer)

    def run(self):
        mouse = keyboard = None
        try:
            self.tid = w.GetCurrentThreadId()
            self.alt_keys_down = {vk for vk in (w.VK_LMENU, w.VK_RMENU) if w.key_down(vk)}
            self.shortcuts.down = {vk for vk in MODIFIERS if vk not in (0x10, 0x11, 0x12) and w.key_down(vk)}
            self.shortcuts.down.update(vk for _, vk in self.shortcuts.bindings if w.key_down(vk))
            msg = W.MSG()
            w.PeekMessage(C.byref(msg), None, 0, 0, 0)
            module = w.GetModuleHandle(None)
            mouse = w.check(w.SetWindowsHookEx(14, self.mouse_callback, module, 0), "WH_MOUSE_LL")
            keyboard = w.check(w.SetWindowsHookEx(13, self.keyboard_callback, module, 0), "WH_KEYBOARD_LL")
            self.ready.set()
            while True:
                result = w.GetMessage(C.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    w.check(False, "GetMessage(hook)")
                if msg.message == w.WM_APP_RESET:
                    if self.gesture and self.gesture.serial == msg.wParam:
                        self.gesture = None
                else:
                    w.TranslateMessage(C.byref(msg))
                    w.DispatchMessage(C.byref(msg))
        except Exception as exc:
            self._fail(exc)
        finally:
            for handle in (keyboard, mouse):
                if handle and not w.UnhookWindowsHookEx(handle):
                    self.error = OSError(C.get_last_error(), "UnhookWindowsHookEx failed")
            self.ready.set()
