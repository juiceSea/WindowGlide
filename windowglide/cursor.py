"""Click-through direction badge beside the real pointer; never changes cursors."""

import ctypes as C
from ctypes import wintypes as W

from . import win32 as w
from . import visual_win32 as v
from .badge_art import render_badge

BADGE_CLASS = "WindowGlide.DirectionBadge"


class CursorFeedback:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.hwnd = None
        self.registered = False
        self.direction = None
        self.geometry = None
        self.size = 32
        self.art_key = None
        self.wndproc = w.WNDPROC(self._wndproc)
        if not enabled:
            return
        try:
            instance = w.GetModuleHandle(None)
            wc = w.WNDCLASS(lpfnWndProc=self.wndproc, hInstance=instance, lpszClassName=BADGE_CLASS)
            w.check(w.RegisterClass(C.byref(wc)), "RegisterClass(direction badge)")
            self.registered = True
            self.hwnd = w.check(w.CreateWindowEx(0x80000 | 0x20 | 0x80 | 0x08000000,
                BADGE_CLASS, "", 0x80000000, 0, 0, 1, 1, None, None, instance, None),
                "CreateWindowEx(direction badge)")
        except Exception:
            self.close()
            raise

    def _wndproc(self, hwnd, message, wp, lp):
        if message == 0x84:
            return -1
        if message == 0x21:
            return 3
        return w.DefWindowProc(hwnd, message, wp, lp)

    def begin(self, direction):
        self.end()
        if not self.enabled:
            return
        self.direction = direction
        w.check(v.SetWindowText(self.hwnd, direction), "SetWindowText(direction)")
        self.ensure()

    def ensure(self):
        if not self.direction:
            return
        point = W.POINT()
        w.check(w.GetCursorPos(C.byref(point)), "GetCursorPos(direction badge)")
        dpi = w.GetDpiForWindow(self.hwnd) or 96
        size = max(24, round(32 * dpi / 96))
        gap = max(12, round(20 * dpi / 96))
        info = w.MONITORINFO(cbSize=C.sizeof(w.MONITORINFO))
        w.check(w.GetMonitorInfo(w.MonitorFromPoint(point, 2), C.byref(info)), "GetMonitorInfo(badge)")
        work = info.rcWork
        x, y = point.x + gap, point.y + gap
        if x + size > work.right:
            x = point.x - gap - size
        if y + size > work.bottom:
            y = point.y - gap - size
        x = max(work.left, min(x, work.right - size))
        y = max(work.top, min(y, work.bottom - size))
        geometry = (x, y, size)
        art_key = (self.direction, size)
        if self.art_key != art_key:
            v.set_layered_pixels(self.hwnd, size, render_badge(*art_key))
            self.art_key = art_key
        if self.geometry == geometry:
            return
        self.size = size
        w.check(w.SetWindowPos(self.hwnd, W.HWND(-1), x, y, size, size, 0x10 | 0x40 | 0x200),
                "SetWindowPos(direction badge)")
        self.geometry = geometry

    def end(self):
        self.direction = None
        self.geometry = None
        if self.hwnd:
            w.ShowWindow(self.hwnd, 0)

    def close(self):
        self.end()
        if self.hwnd:
            w.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.registered:
            w.UnregisterClass(BADGE_CLASS, w.GetModuleHandle(None))
            self.registered = False
