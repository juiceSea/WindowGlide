"""Message-driven controller. A watchdog exists only during a gesture."""

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import logging
import queue

from . import win32 as w
from .hooks import Hooks
from .window_manager import WindowManager, Target, Movement, Resizing
from .config import VisualSettings
from .overlay import Overlay
from .cursor import CursorFeedback
from .shortcuts import bindings_for
from .window_actions import WindowActions

log = logging.getLogger(__name__)


@dataclass
class Session:
    serial: int
    target: Target
    origin: tuple[int, int]
    operation: Movement | Resizing | None = None
    foreground: int | None = None
    kind: str = "move"
    glass_color: str = "#FFFFFF"


class AlreadyRunning(RuntimeError):
    pass


class Application:
    def __init__(self, smoke_seconds=0, test_input=False, settings=None):
        self.smoke_seconds, self.test_input = smoke_seconds, test_input
        self.settings = settings or VisualSettings()
        self.overlay = self.cursor = None
        self.window_actions = None
        self.hwnd = self.mutex = self.hooks = None
        self.hotkey = self.registered_class = False
        self.commands = queue.SimpleQueue()
        self.session = None
        self.exit_code = 0
        self.wndproc = w.WNDPROC(self._wndproc)

    def _wndproc(self, hwnd, message, wp, lp):
        try:
            if message == w.WM_APP_ACTION:
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    self._command(command)
                return 0
            if message == w.WM_TIMER:
                if wp == 2:
                    log.info("Smoke deadline reached")
                    w.PostQuitMessage(0)
                elif wp == 1:
                    self._watchdog()
                elif wp == 3:
                    w.KillTimer(self.hwnd, 3)
                    self.hooks.motion_pending = False
                    latest = self.hooks.latest_position
                    if self.session and latest and latest[0] == self.session.serial:
                        self._update(latest[1])
                elif wp == WindowActions.TIMER and self.window_actions:
                    self.window_actions.tick()
                return 0
            if message == w.WM_HOTKEY and wp == 1 or message == w.WM_CLOSE:
                log.info("Exit requested")
                w.PostQuitMessage(0)
                return 0
            if message == w.WM_DESTROY:
                w.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("Controller failure; shutting down safely")
            self.exit_code = 1
            w.PostQuitMessage(1)
        return w.DefWindowProc(hwnd, message, wp, lp)

    def _command(self, command):
        kind, *args = command
        if kind == "window_event":
            if self.window_actions:
                self.window_actions.handle_event(*args)
            return
        if kind == "shortcut":
            self.finish("window shortcut")
            if self.window_actions:
                self.window_actions.execute(*args)
            return
        if kind == "visual_event":
            s = self.session
            if s and s.operation and s.target.hwnd == args[0]:
                if not s.target.alive() or not w.IsWindowVisible(s.target.hwnd) or w.IsIconic(s.target.hwnd):
                    self.finish("target closed, hidden or minimized")
                elif s.foreground != w.GetForegroundWindow():
                    self.finish("foreground changed")
                else:
                    self._sync_feedback()
            return
        if kind == "hook_error":
            raise RuntimeError(f"Input hook failed: {args[0]}")
        if kind == "mask_failed":
            log.warning("Alt menu mask was not fully delivered (error=%s); physical Alt release passed through", args[0])
            return
        if kind == "armed":
            serial, hwnd, origin = args[:3]
            operation_kind = args[3] if len(args) > 3 else "move"
            self.finish("superseded")
            try:
                target = self.manager.inspect(hwnd)
            except (OSError, ValueError) as exc:
                log.info("Target skipped hwnd=0x%X reason=%s", hwnd, exc)
                self.hooks.reset(serial)
                return
            self.session = Session(serial, target, origin, kind=operation_kind)
            w.check(w.SetTimer(self.hwnd, 1, 100, None), "SetTimer(active watchdog)")
            log.info("%s armed hwnd=0x%X title=%r", operation_kind.capitalize(), hwnd, target.title)
            return
        if not self.session or self.session.serial != args[0]:
            if kind == "motion":
                self.hooks.motion_pending = False
            return
        if kind == "start":
            try:
                if self.overlay:
                    # Sample before moving/restoring the target, while our feedback
                    # is still hidden. Never re-sample during this gesture.
                    try:
                        self.session.glass_color = self.overlay.choose_glass_color(
                            self.session.target, self.session.origin, self.session.kind == "resize")
                    except Exception:
                        log.exception("Adaptive glass unavailable; keeping white without interrupting movement")
                begin = self.manager.begin_resize if self.session.kind == "resize" else self.manager.begin_move
                self.session.operation = begin(self.session.target, self.session.origin, args[1])
                self.session.foreground = w.GetForegroundWindow()
                self._start_feedback()
            except (OSError, ValueError) as exc:
                log.warning("%s could not start: %s", self.session.kind.capitalize(), exc)
                self.finish("start failed")
        elif kind == "finish":
            self.finish(args[1], args[2])
        elif kind == "motion":
            w.check(w.SetTimer(self.hwnd, 3, 16, None), "SetTimer(coalesced move)")

    def _update(self, point):
        if self.session and self.session.operation:
            try:
                self.manager.update_position(self.session.target, self.session.operation, point)
                self._sync_feedback()
            except (OSError, ValueError) as exc:
                log.warning("Position update failed: %s", exc)
                self.finish("position update failed")

    def _watchdog(self):
        s = self.session
        if not s:
            return
        if not s.target.alive() or w.IsIconic(s.target.hwnd):
            self.finish("target closed or minimized")
        elif w.IsHungAppWindow(s.target.hwnd):
            self.finish("target stopped responding")
        elif not w.key_down(w.VK_MENU):
            self.finish("modifier no longer held")
        elif s.operation and s.foreground != w.GetForegroundWindow():
            self.finish("foreground changed")
        else:
            self._sync_feedback()

    def _post_visual_event(self, hwnd):
        self.commands.put(("visual_event", hwnd))
        w.PostMessage(self.hwnd, w.WM_APP_ACTION, 0, 0)

    def _post_window_event(self, command):
        self.commands.put(command)
        w.PostMessage(self.hwnd, w.WM_APP_ACTION, 0, 0)

    def _start_feedback(self):
        s = self.session
        if not s or not s.operation:
            return  # The inactive resize center has no active-operation visuals.
        if self.overlay:
            try:
                self.overlay.show_for(s.target, s.glass_color)
            except Exception:
                log.exception("Overlay unavailable for this gesture; movement remains enabled")
                self.overlay.hide()
        if self.cursor:
            try:
                self.cursor.begin(s.operation.direction if isinstance(s.operation, Resizing) else "move")
            except Exception:
                log.exception("Cursor feedback unavailable for this gesture")

    def _sync_feedback(self):
        if self.overlay:
            try:
                self.overlay.sync()
            except Exception:
                log.exception("Overlay follow failed; hiding it without interrupting movement")
                self.overlay.hide()
        if self.cursor:
            try:
                self.cursor.ensure()
            except Exception:
                log.exception("Cursor feedback failed")
                self.cursor.end()

    def _hide_feedback(self):
        for feedback, method in ((self.overlay, "hide"), (self.cursor, "end")):
            if feedback:
                try:
                    getattr(feedback, method)()
                except Exception:
                    log.exception("Visual feedback cleanup failed")

    def finish(self, reason, final_point=None):
        s, self.session = self.session, None
        self._hide_feedback()
        if not s:
            return
        w.KillTimer(self.hwnd, 1)
        w.KillTimer(self.hwnd, 3)
        self.hooks.motion_pending = False
        if s.operation and final_point:
            try:
                self.manager.update_position(s.target, s.operation, final_point)
            except (OSError, ValueError) as exc:
                log.info("Final position skipped: %s", exc)
        self.hooks.reset(s.serial)
        log.info("%s ended hwnd=0x%X reason=%s", s.kind.capitalize(), s.target.hwnd, reason)

    def run(self, initialize=None):
        w.dpi_awareness()
        self.mutex = w.check(w.CreateMutex(None, False, w.MUTEX_NAME), "CreateMutex")
        if C.get_last_error() == 183:
            w.CloseHandle(self.mutex)
            self.mutex = None
            raise AlreadyRunning("WindowGlide is already running")
        try:
            if initialize:
                initialize(self)
            self.manager = WindowManager()
            instance = w.GetModuleHandle(None)
            wc = w.WNDCLASS(lpfnWndProc=self.wndproc, hInstance=instance, lpszClassName=w.CLASS_NAME)
            w.check(w.RegisterClass(C.byref(wc)), "RegisterClass")
            self.registered_class = True
            self.hwnd = w.check(w.CreateWindowEx(0x80 | 0x08000000, w.CLASS_NAME, "WindowGlide",
                                0, 0, 0, 0, 0, None, None, instance, None), "CreateWindowEx(control)")
            w.check(w.RegisterHotKey(self.hwnd, 1, 0x4000 | 1 | 2 | 8, ord("Q")),
                    "RegisterHotKey(Ctrl+Win+Alt+Q); background startup aborted")
            self.hotkey = True
            self.overlay = Overlay(self.settings, self._post_visual_event)
            self.cursor = CursorFeedback(self.settings.enable_cursor_change)
            if self.settings.enable_window_shortcuts:
                self.window_actions = WindowActions(self.hwnd, self.manager, self._post_window_event, self.test_input)
                log.info("Window shortcuts enabled priority=keyboard-hook minimize=%s restore=%s maximize=%s",
                         self.settings.shortcut_minimize, self.settings.shortcut_restore, self.settings.shortcut_maximize)
            else:
                log.info("Window shortcuts disabled")
            self.hooks = Hooks(self.hwnd, self.commands, self.test_input, bindings_for(self.settings))
            self.hooks.start()
            if not self.hooks.ready.wait(5) or self.hooks.error:
                raise RuntimeError(f"Hook registration failed: {self.hooks.error}")
            log.info("READY pid=%s hooks=mouse,keyboard DPI=PerMonitorV2 exit=Ctrl+Win+Alt+Q test_input=%s",
                     w.GetCurrentProcessId(), self.test_input)
            if self.smoke_seconds:
                w.check(w.SetTimer(self.hwnd, 2, int(self.smoke_seconds * 1000), None), "SetTimer(smoke)")
            msg = W.MSG()
            while True:
                result = w.GetMessage(C.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    w.check(False, "GetMessage(controller)")
                w.TranslateMessage(C.byref(msg))
                w.DispatchMessage(C.byref(msg))
            return self.exit_code
        except Exception:
            log.exception("Startup/runtime failure")
            raise
        finally:
            self.cleanup()

    def cleanup(self):
        self.finish("application exit")
        if self.hooks:
            self.hooks.stop()
            self.hooks.join(timeout=3)
            if self.hooks.is_alive():
                log.error("Hook thread did not stop before deadline; process exit will release hooks")
            elif self.hooks.error:
                log.error("Hook cleanup status: %r", self.hooks.error)
            else:
                log.info("Mouse and keyboard hooks unregistered")
        if self.hotkey:
            w.UnregisterHotKey(self.hwnd, 1)
            self.hotkey = False
        if self.window_actions:
            self.window_actions.close()
            self.window_actions = None
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.hwnd:
            w.KillTimer(self.hwnd, 1)
            w.KillTimer(self.hwnd, 2)
            w.KillTimer(self.hwnd, 3)
            w.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.registered_class:
            w.UnregisterClass(w.CLASS_NAME, w.GetModuleHandle(None))
        log.info("STOPPED; resources released")
        logging.shutdown()
        if self.mutex:
            w.CloseHandle(self.mutex)
            self.mutex = None


def request_stop():
    hwnd = w.FindWindow(w.CLASS_NAME, None)
    if not hwnd:
        return False
    w.check(w.PostMessage(hwnd, w.WM_CLOSE, 0, 0), "PostMessage(stop)")
    return True
