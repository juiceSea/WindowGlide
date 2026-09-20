"""Window shortcuts and a bounded, event-driven recent-minimize stack."""

import ctypes as C
from ctypes import wintypes as W
from collections import deque
from dataclasses import dataclass
import logging
import time

from . import win32 as w
from .window_manager import SHELL_CLASSES, Target, window_class

log = logging.getLogger(__name__)


@dataclass
class Minimized:
    target: Target
    maximized: bool


class MinimizedStack:
    def __init__(self):
        self.entries = []

    def remove(self, hwnd):
        self.entries[:] = [entry for entry in self.entries if entry.target.hwnd != hwnd]

    def push(self, entry):
        self.remove(entry.target.hwnd)
        self.entries.append(entry)
        del self.entries[:-100]

    def pop(self):
        return self.entries.pop() if self.entries else None


@dataclass
class Pending:
    action: str
    target: Target
    activate: Target | None
    foreground: int
    deadline: float
    cancelled: bool = False


class WindowActions:
    TIMER = 4

    def __init__(self, hwnd, manager, post_event, test_input=False):
        self.hwnd, self.manager, self.post_event = hwnd, manager, post_event
        self.test_input = test_input
        self.stack = MinimizedStack()
        self.own_minimizes = {}
        self.hooks = []
        self.pending = None
        self.queued = deque(maxlen=32)
        self.eventproc = w.WINEVENTPROC(self._event)
        try:
            for event in (0x16, 0x8001):  # MINIMIZESTART, OBJECT_DESTROY
                self.hooks.append(w.check(w.SetWinEventHook(event, event, None, self.eventproc, 0, 0, 2),
                                         "SetWinEventHook(window shortcuts)"))
        except Exception:
            self.close()
            raise

    def _event(self, hook, event, hwnd, obj, child, tid, timestamp):
        if hwnd and obj == 0 and child == 0:
            pending_window = self.pending and (self.pending.target.hwnd == hwnd or
                             self.pending.activate and self.pending.activate.hwnd == hwnd)
            if event == 0x16 or pending_window or any(entry.target.hwnd == hwnd for entry in self.stack.entries):
                self.post_event(("window_event", event, hwnd))

    def inspect(self, hwnd):
        if not hwnd or hwnd in (w.GetDesktopWindow(), w.GetShellWindow()):
            raise ValueError("Desktop or shell is excluded")
        if w.GetAncestor(hwnd, 2) != hwnd or not w.IsWindowVisible(hwnd):
            raise ValueError("Not a visible top-level window")
        if w.GetWindowLongPtr(hwnd, -20) & 0x80 or window_class(hwnd) in SHELL_CLASSES:
            raise ValueError("Tool or system window is excluded")
        if self.test_input and window_class(hwnd) != "WindowGlide.AutomationFixture":
            raise ValueError("Test mode only operates on disposable fixtures")
        target = self.manager.inspect(hwnd)
        if target.pid == w.GetCurrentProcessId() or not target.title:
            raise ValueError("Own or untitled background window is excluded")
        return target

    def record(self, target):
        placement = w.WINDOWPLACEMENT(length=C.sizeof(w.WINDOWPLACEMENT))
        w.check(w.GetWindowPlacement(target.hwnd, C.byref(placement)), "GetWindowPlacement(shortcuts)")
        return Minimized(target, bool(w.IsZoomed(target.hwnd) or placement.flags & 2))

    def handle_event(self, event, hwnd):
        if event == 0x8001:
            self.stack.remove(hwnd)
            self.own_minimizes.pop(hwnd, None)
            if self.pending:
                if self.pending.target.hwnd == hwnd:
                    self.pending.cancelled = True
                if self.pending.activate and self.pending.activate.hwnd == hwnd:
                    self.pending.activate = None
            return
        try:
            target = self.inspect(hwnd)
            entry = self.record(target)
            # Our explicit minimize saved the pre-minimized state already.
            previous = self.own_minimizes.pop(hwnd, None)
            if previous and previous.target.pid == target.pid and previous.target.tid == target.tid:
                entry.maximized = previous.maximized
            self.stack.push(entry)
            log.info("Minimize tracked hwnd=0x%X maximized=%s stack=%s", hwnd, entry.maximized, len(self.stack.entries))
        except (OSError, ValueError):
            pass  # Ordinary excluded desktop/tool/privileged windows are not errors.

    def next_window(self, current):
        # Z order first, then wrap. Query only suitable normal windows.
        candidates = []
        seen = set()
        for first in (w.GetWindow(current, 2), w.GetTopWindow(None)):
            hwnd = first
            while hwnd and hwnd not in seen and len(seen) < 1000:
                seen.add(hwnd)
                if hwnd != current and not w.IsIconic(hwnd):
                    candidates.append(hwnd)
                hwnd = w.GetWindow(hwnd, 2)
        for hwnd in candidates:
            try:
                return self.inspect(hwnd)
            except (OSError, ValueError):
                continue
        return None

    def execute(self, action, hwnd):
        if self.pending:
            self.queued.append((action, hwnd))
            return
        try:
            foreground = w.GetForegroundWindow()
            if action == "restore":
                while entry := self.stack.pop():
                    if not entry.target.alive() or not w.IsIconic(entry.target.hwnd):
                        continue
                    try:
                        target = self.inspect(entry.target.hwnd)
                    except (OSError, ValueError):
                        continue
                    w.check(w.ShowWindowAsync(target.hwnd, 3 if entry.maximized else 9), "ShowWindowAsync(restore)")
                    self._wait(action, target, target, foreground)
                    log.info("Shortcut restore hwnd=0x%X maximized=%s", target.hwnd, entry.maximized)
                    return
                log.info("Shortcut restore: no eligible minimized windows")
                return
            target = self.inspect(hwnd)
            if w.IsIconic(hwnd):
                return
            style = w.GetWindowLongPtr(hwnd, -16)
            if action == "minimize":
                if not style & 0x20000:
                    raise ValueError("Window does not advertise minimization")
                entry, next_target = self.record(target), self.next_window(hwnd)
                w.check(w.ShowWindowAsync(hwnd, 6), "ShowWindowAsync(minimize)")
                self.own_minimizes[hwnd] = entry
                while len(self.own_minimizes) > 100:
                    self.own_minimizes.pop(next(iter(self.own_minimizes)))
                self.stack.push(entry)
                self._wait(action, target, next_target, foreground)
            elif action == "maximize":
                if not style & 0x10000:
                    raise ValueError("Window does not advertise maximization")
                if not w.IsZoomed(hwnd):
                    w.check(w.ShowWindowAsync(hwnd, 3), "ShowWindowAsync(maximize)")
                    self._wait(action, target, None, foreground)
            else:
                raise ValueError("Unknown shortcut action")
            log.info("Shortcut %s hwnd=0x%X", action, hwnd)
        except (OSError, ValueError) as exc:
            log.info("Shortcut %s skipped: %s", action, exc)

    def _wait(self, action, target, activate, foreground):
        self.pending = Pending(action, target, activate, foreground, time.monotonic() + 1.5)
        w.check(w.SetTimer(self.hwnd, self.TIMER, 25, None), "SetTimer(window action)")

    def tick(self):
        pending = self.pending
        if not pending:
            w.KillTimer(self.hwnd, self.TIMER)
            return
        alive = not pending.cancelled and pending.target.alive()
        complete = alive and {"minimize": bool(w.IsIconic(pending.target.hwnd)),
                             "restore": not w.IsIconic(pending.target.hwnd),
                             "maximize": bool(w.IsZoomed(pending.target.hwnd))}[pending.action]
        if not complete and alive and time.monotonic() < pending.deadline:
            return
        self.pending = None
        w.KillTimer(self.hwnd, self.TIMER)
        if complete and pending.activate and pending.activate.alive():
            foreground = w.GetForegroundWindow()
            allowed = (pending.foreground, pending.target.hwnd, pending.activate.hwnd,
                       w.GetDesktopWindow(), w.GetShellWindow(), None)
            # Minimizing can make Windows activate an unrelated window before
            # this timer runs. This shortcut explicitly requests the next normal
            # window, so still make one policy-respecting activation attempt.
            if (pending.action == "minimize" or foreground in allowed) and not w.IsIconic(pending.activate.hwnd):
                if not w.SetForegroundWindow(pending.activate.hwnd):
                    log.info("Shortcut focus request declined by Windows")
            else:
                log.info("Shortcut focus unchanged because foreground moved elsewhere")
        elif not complete:
            self.own_minimizes.pop(pending.target.hwnd, None)
            log.info("Shortcut %s not confirmed before deadline or window closed", pending.action)
        while self.queued and not self.pending:
            self.execute(*self.queued.popleft())

    def close(self):
        w.KillTimer(self.hwnd, self.TIMER)
        for hook in self.hooks:
            w.UnhookWinEvent(hook)
        self.hooks.clear()
        self.stack.entries.clear()
        self.own_minimizes.clear()
        self.queued.clear()
        self.pending = None
