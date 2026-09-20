"""Dedicated input thread. Callbacks do no disk I/O or synchronous cross-process messaging."""

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import threading
import time

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
    button: str = "left"
    requires_shift: bool = False


@dataclass
class DeferredShortcut:
    action: str
    hwnd: int
    pid: int
    tid: int
    keys: frozenset[int]
    deadline: float
    ready_at: float | None = None


class Hooks(threading.Thread):
    def __init__(self, control_hwnd, commands, test_input=False, shortcuts=None, drag_modifier="Alt", enable_shift_left_resize=False):
        super().__init__(name="InputHook", daemon=True)
        if drag_modifier not in ("Alt", "Win"):
            raise ValueError('drag_modifier must be "Alt" or "Win"')
        self.drag_modifier = drag_modifier
        self.enable_shift_left_resize = enable_shift_left_resize
        self.modifier_keys = (w.VK_MENU, w.VK_LMENU, w.VK_RMENU) if drag_modifier == "Alt" else (0x5B, 0x5C)
        self.excluded_modifiers = (0x11, 0x10, 0x5B, 0x5C) if drag_modifier == "Alt" else (0x11, 0x10, w.VK_MENU)
        self.control_hwnd, self.commands = control_hwnd, commands
        self.test_input = test_input
        self.shortcuts = ShortcutMatcher(shortcuts or {})
        self.shortcut_mask = False
        self.deferred_shortcut = None
        self.shortcut_timer = None
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
        # Keep masking until the whole modifier press ends, even after Esc/reset.
        self.mask_modifier_on_release = False
        self.modifier_keys_down = set()
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

    def _clear_deferred_shortcut(self, reason=None):
        pending, self.deferred_shortcut = self.deferred_shortcut, None
        if self.shortcut_timer:
            w.KillTimer(None, self.shortcut_timer)
            self.shortcut_timer = None
        if pending and reason:
            self.submit("shortcut_cancelled", pending.action, reason)

    def _defer_shortcut(self, action, vk):
        # Keep the original target; never re-target after the synthetic batch.
        hwnd = w.GetForegroundWindow()
        pid = W.DWORD()
        tid = w.GetWindowThreadProcessId(hwnd, C.byref(pid)) if hwnd else 0
        if not tid:
            return
        self.deferred_shortcut = DeferredShortcut(
            action, hwnd, pid.value, tid,
            frozenset(key for key in self.shortcuts.down if key in MODIFIERS or key == vk),
            time.monotonic() + 1.5,
        )
        self.shortcut_timer = w.check(w.SetTimer(None, 0, 15, None), "SetTimer(deferred shortcut)")

    def _poll_deferred_shortcut(self):
        pending = self.deferred_shortcut
        if not pending:
            return
        now = time.monotonic()
        pid = W.DWORD()
        tid = w.GetWindowThreadProcessId(pending.hwnd, C.byref(pid))
        if (w.GetForegroundWindow() != pending.hwnd or
                (tid, pid.value) != (pending.tid, pending.pid)):
            self._clear_deferred_shortcut("target or foreground changed")
        elif now >= pending.deadline:
            self._clear_deferred_shortcut("input release timed out")
        elif pending.ready_at is not None and now >= pending.ready_at:
            self._clear_deferred_shortcut()
            self.submit("deferred_shortcut", pending.action, pending.hwnd, pending.pid, pending.tid)

    def _mouse(self, code, message, pointer):
        if code < 0:
            return w.CallNextHookEx(None, code, message, pointer)
        try:
            event = C.cast(pointer, C.POINTER(w.MSLLHOOKSTRUCT)).contents
            if not self._accept(event.flags, event.dwExtraInfo, 1):
                return w.CallNextHookEx(None, code, message, pointer)
            if message in (w.WM_LBUTTONDOWN, w.WM_RBUTTONDOWN):
                button = "left" if message == w.WM_LBUTTONDOWN else "right"
                eat_attribute = "eat_left_up" if button == "left" else "eat_right_up"
                if self.gesture:
                    # A second button cannot open a menu or switch the active gesture.
                    setattr(self, eat_attribute, True)
                    return 1
                can_start = not (self.eat_left_up or self.eat_right_up) and any(w.key_down(vk) for vk in self.modifier_keys)
                shift_resize = self.enable_shift_left_resize and button == "left" and w.key_down(0x10)
                kind = "resize" if button == "right" or shift_resize else "move"
                # Avoid AltGr and other modified mouse shortcuts.
                if can_start and not any(w.key_down(vk) for vk in self.excluded_modifiers if not (shift_resize and vk == 0x10)):
                    hwnd = candidate_at(event.pt.x, event.pt.y, resizing=kind == "resize")
                    if hwnd and self.test_input and window_class(hwnd) != "WindowGlide.AutomationFixture":
                        hwnd = None
                    if hwnd:
                        self.serial += 1
                        self.gesture = Gesture(self.serial, hwnd, (event.pt.x, event.pt.y), kind=kind,
                                               button=button, requires_shift=shift_resize)
                        if kind == "resize" or self.drag_modifier == "Win":
                            # Includes inactive resize center and Win clicks without
                            # motion: consumed input must not activate a native menu.
                            self.mask_modifier_on_release = True
                        self.latest_position = (self.serial, self.gesture.origin)
                        setattr(self, eat_attribute, True)
                        self.submit("armed", self.serial, hwnd, self.gesture.origin, kind, shift_resize)
                        return 1
            elif message == w.WM_MOUSEMOVE and self.gesture:
                g = self.gesture
                self.latest_position = (g.serial, (event.pt.x, event.pt.y))
                if not g.started and (abs(event.pt.x - g.origin[0]) >= self.drag_x or abs(event.pt.y - g.origin[1]) >= self.drag_y):
                    g.started = True
                    self.mask_modifier_on_release = True
                    self.submit("start", g.serial, (event.pt.x, event.pt.y))
                elif g.started and not self.motion_pending:
                    self.motion_pending = True
                    self.submit("motion", g.serial)
            elif message in (w.WM_LBUTTONUP, w.WM_RBUTTONUP):
                button = "left" if message == w.WM_LBUTTONUP else "right"
                eat_attribute = "eat_left_up" if button == "left" else "eat_right_up"
                if not getattr(self, eat_attribute):
                    return w.CallNextHookEx(None, code, message, pointer)
                setattr(self, eat_attribute, False)
                if self.gesture and self.gesture.button == button:
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
                # New input supersedes a waiting action rather than accumulating
                # stale window commands. Auto-repeat of held keys is harmless.
                if self.deferred_shortcut and not up and event.vkCode not in self.shortcuts.down:
                    self._clear_deferred_shortcut("new input before dispatch")
                consumed, action = self.shortcuts.feed(event.vkCode, up)
                if action:
                    self.shortcut_mask = True
                    if not mask_alt_menu():
                        self.submit("mask_failed", C.get_last_error())
                    if event.flags & 0x10:
                        self._defer_shortcut(action, event.vkCode)
                    else:
                        self.submit("shortcut", action, w.GetForegroundWindow())
                if up and self.shortcut_mask and MODIFIERS.get(event.vkCode) in ("Alt", "Win"):
                    if not mask_alt_menu():
                        self.submit("mask_failed", C.get_last_error())
                if not any(key in MODIFIERS for key in self.shortcuts.down):
                    self.shortcut_mask = False
                pending = self.deferred_shortcut
                if pending and pending.ready_at is None and not pending.keys.intersection(self.shortcuts.down):
                    # Post-release settling occurs on this thread's message loop,
                    # after callbacks and menu-mask input, never via a hook sleep.
                    pending.ready_at = time.monotonic() + 0.05
                if consumed:
                    return 1
            if not self._accept(event.flags, event.dwExtraInfo, 0x10):
                return w.CallNextHookEx(None, code, message, pointer)
            if up and event.vkCode in (0x10, 0xA0, 0xA1) and self.gesture and self.gesture.requires_shift:
                self.submit("finish", self.gesture.serial, "shift released", self.latest_position[1])
                self.gesture = None
            is_modifier = event.vkCode in self.modifier_keys
            if is_modifier and not up:
                if not self.modifier_keys_down:
                    self.mask_modifier_on_release = False
                self.modifier_keys_down.add(event.vkCode)
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
            if up and is_modifier:
                if self.gesture:
                    self.submit("finish", self.gesture.serial, f"{self.drag_modifier.lower()} released", self.latest_position[1])
                    self.gesture = None
                if self.mask_modifier_on_release and not mask_alt_menu():
                    self.submit("mask_failed", C.get_last_error())
                self.modifier_keys_down.discard(event.vkCode)
                if not self.modifier_keys_down:
                    self.mask_modifier_on_release = False
        except Exception as exc:
            self._fail(exc)
        return w.CallNextHookEx(None, code, message, pointer)

    def run(self):
        mouse = keyboard = None
        try:
            self.tid = w.GetCurrentThreadId()
            self.modifier_keys_down = {vk for vk in self.modifier_keys if vk != w.VK_MENU and w.key_down(vk)}
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
                elif msg.message == w.WM_TIMER and msg.wParam == self.shortcut_timer:
                    self._poll_deferred_shortcut()
                else:
                    w.TranslateMessage(C.byref(msg))
                    w.DispatchMessage(C.byref(msg))
        except Exception as exc:
            self._fail(exc)
        finally:
            self._clear_deferred_shortcut()
            for handle in (keyboard, mouse):
                if handle and not w.UnhookWindowsHookEx(handle):
                    self.error = OSError(C.get_last_error(), "UnhookWindowsHookEx failed")
            self.ready.set()
