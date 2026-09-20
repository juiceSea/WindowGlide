"""Two click-through, non-activating native layered windows.

Windows paints a white rounded layer and a separate configurable opaque ring.
Regions are rebuilt only when size/DPI changes; moving needs no bitmap redraw.
"""

import ctypes as C
from ctypes import wintypes as W
import logging

from . import win32 as w
from . import visual_win32 as v
from .window_manager import visible_rect
from .accent import BorderColor
from .glass import WHITE, sample_glass
from .resize import direction_at

log = logging.getLogger(__name__)
BORDER_CLASS = "WindowGlide.Overlay.Border"
GLASS_CLASS = "WindowGlide.Overlay.Glass"


def rounded_region(left, top, right, bottom, radius):
    if radius <= 0:
        return w.check(v.CreateRectRgn(left, top, right, bottom), "CreateRectRgn")
    return w.check(v.CreateRoundRectRgn(left, top, right, bottom, radius * 2, radius * 2), "CreateRoundRectRgn")


class Overlay:
    def __init__(self, settings, on_event):
        self.settings, self.on_event = settings, on_event
        self.border_colors = BorderColor(settings)
        self.border_color = settings.border_color
        self.glass_color = WHITE
        self.windows = {}
        self.registered = []
        self.event_hooks = []
        self.target = None
        self.geometry = None
        self.region_geometry = None
        self.pending = False
        self.wndproc = w.WNDPROC(self._wndproc)
        self.eventproc = w.WINEVENTPROC(self._eventproc)
        try:
            if settings.enable_border:
                self._create(BORDER_CLASS, v.color_ref(settings.border_color), 255)
            if settings.enable_glass and settings.glass_opacity > 0:
                self._create(GLASS_CLASS, 0xFFFFFF, round(settings.glass_opacity * 255))
        except Exception:
            self.close()
            raise

    def _wndproc(self, hwnd, message, wp, lp):
        if message == 0x84:  # WM_NCHITTEST; layered+transparent also crosses process boundaries.
            return -1
        if message == 0x21:  # WM_MOUSEACTIVATE
            return 3
        return w.DefWindowProc(hwnd, message, wp, lp)

    def _create(self, name, color, opacity):
        instance = w.GetModuleHandle(None)
        brush = w.check(v.CreateSolidBrush(color), "CreateSolidBrush(overlay)")
        wc = w.WNDCLASS(lpfnWndProc=self.wndproc, hInstance=instance, lpszClassName=name, hbrBackground=brush)
        if not w.RegisterClass(C.byref(wc)):
            v.DeleteObject(brush)
            w.check(False, "RegisterClass(overlay)")
        # The system owns and deletes a registered class background brush.
        self.registered.append(name)
        ex_style = 0x80000 | 0x20 | 0x80 | 0x08000000  # layered, transparent, tool, no-activate
        hwnd = w.check(w.CreateWindowEx(ex_style, name, "", 0x80000000,
                        0, 0, 1, 1, None, None, instance, None), "CreateWindowEx(overlay)")
        self.windows[name] = hwnd
        w.check(v.SetLayeredWindowAttributes(hwnd, 0, opacity, 2), "SetLayeredWindowAttributes")
        log.info("Overlay created kind=%s hwnd=0x%X", name, hwnd)

    def _eventproc(self, hook, event, hwnd, obj, child, tid, timestamp):
        if not self.target:
            return
        relevant = event == 3 or (hwnd == self.target.hwnd and obj == 0 and child == 0
                                  and event in (0x8001, 0x8003, 0x800B))
        if relevant and not self.pending:
            self.pending = True
            try:
                self.on_event(self.target.hwnd)
            except Exception:
                log.exception("Overlay event dispatch failed")

    def choose_glass_color(self, target, origin, resizing):
        if GLASS_CLASS not in self.windows or not self.settings.adaptive_glass_color:
            return WHITE
        if resizing and direction_at(visible_rect(target.hwnd), origin) is None:
            return WHITE
        result = sample_glass(target.hwnd)
        log.info("Glass choice color=%s reason=%s sample_ms=%.2f", result.color, result.reason, result.elapsed_ms)
        return result.color

    def show_for(self, target, glass_color=WHITE):
        self.hide()
        if not self.windows:
            return
        self.target = target
        try:
            self._refresh_border_color()
            if GLASS_CLASS in self.windows and self.glass_color != glass_color:
                self._replace_background(GLASS_CLASS, glass_color)
                self.glass_color = glass_color
            self.event_hooks.append(w.check(w.SetWinEventHook(0x8001, 0x800B, None, self.eventproc,
                                           target.pid, target.tid, 2), "SetWinEventHook(overlay target)"))
            self.event_hooks.append(w.check(w.SetWinEventHook(3, 3, None, self.eventproc, 0, 0, 2),
                                           "SetWinEventHook(foreground)"))
            self.sync(force=True)
            log.info("Overlay shown target=0x%X", target.hwnd)
        except Exception:
            self.hide()
            raise

    def _refresh_border_color(self):
        hwnd = self.windows.get(BORDER_CLASS)
        if not hwnd:
            return
        color = self.border_colors.resolve()
        if color == self.border_color:
            return
        self._replace_background(BORDER_CLASS, color)
        self.border_color = color
        log.info("Border color updated color=%s windows_accent=%s", color, self.settings.use_windows_accent_color)

    def _replace_background(self, name, color):
        hwnd = self.windows[name]
        brush = w.check(v.CreateSolidBrush(v.color_ref(color)), "CreateSolidBrush(accent)")
        previous = v.SetClassLongPtr(hwnd, -10, brush)  # GCLP_HBRBACKGROUND
        if not previous:
            v.DeleteObject(brush)
            w.check(False, "SetClassLongPtr(border brush)")
        # Only the new brush remains owned by the window class.
        v.DeleteObject(previous)
        v.InvalidateRect(hwnd, None, True)

    def _set_region(self, hwnd, width, height, radius, border=0):
        outer = rounded_region(0, 0, width, height, radius)
        inner = None
        try:
            if border:
                inner = rounded_region(border, border, width - border, height - border, max(0, radius - border))
                w.check(v.CombineRgn(outer, outer, inner, 4), "CombineRgn(border)")
            w.check(v.SetWindowRgn(hwnd, outer, True), "SetWindowRgn(overlay)")
            outer = None  # Ownership transferred to Windows.
        finally:
            if outer:
                v.DeleteObject(outer)
            if inner:
                v.DeleteObject(inner)

    def sync(self, force=False):
        self.pending = False
        target = self.target
        if not target:
            return
        if not target.alive() or not w.IsWindowVisible(target.hwnd) or w.IsIconic(target.hwnd):
            self.hide()
            return
        left, top, right, bottom = visible_rect(target.hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            self.hide()
            return
        dpi = w.GetDpiForWindow(target.hwnd) or 96
        border = max(1, round(self.settings.border_width * dpi / 96))
        radius = round(self.settings.corner_radius * dpi / 96)
        corner_preference = W.DWORD()
        if w.IsZoomed(target.hwnd) or (w.DwmGetWindowAttribute(target.hwnd, 33, C.byref(corner_preference), 4) == 0
                                      and corner_preference.value == 1):
            radius = 0
        radius = min(radius, width // 2, height // 2)
        region_geometry = (width, height, border, radius)
        if self.region_geometry != region_geometry:
            if BORDER_CLASS in self.windows:
                self._set_region(self.windows[BORDER_CLASS], width + 2 * border, height + 2 * border,
                                 radius + border if radius else 0, border)
            if GLASS_CLASS in self.windows:
                self._set_region(self.windows[GLASS_CLASS], width, height, radius)
            self.region_geometry = region_geometry
        own = set(self.windows.values())
        predecessor = v.GetWindow(target.hwnd, 3)  # GW_HWNDPREV
        while predecessor in own:
            predecessor = v.GetWindow(predecessor, 3)
        target_topmost = bool(w.GetWindowLongPtr(target.hwnd, -20) & 8)
        geometry = (left, top, right, bottom, dpi, radius, predecessor, target_topmost)
        if not force and self.geometry == geometry:
            return
        for name in (BORDER_CLASS, GLASS_CLASS):
            hwnd = self.windows.get(name)
            if not hwnd:
                continue
            if bool(w.GetWindowLongPtr(hwnd, -20) & 8) != target_topmost:
                w.check(w.SetWindowPos(hwnd, W.HWND(-1 if target_topmost else -2), 0, 0, 0, 0,
                                       1 | 2 | 0x10 | 0x200), "SetWindowPos(overlay band)")
            after = predecessor
            if not target_topmost and after and w.GetWindowLongPtr(after, -20) & 8:
                after = None  # Top of normal windows, below the topmost band.
            padding = border if name == BORDER_CLASS else 0
            w.check(w.SetWindowPos(hwnd, after, left - padding, top - padding,
                                   width + 2 * padding, height + 2 * padding, 0x10 | 0x40 | 0x200),
                    "SetWindowPos(overlay follow)")
            predecessor = hwnd
        self.geometry = geometry

    def hide(self):
        was_active = self.target is not None
        self.target = None
        self.pending = False
        for hook in self.event_hooks:
            w.UnhookWinEvent(hook)
        self.event_hooks.clear()
        for hwnd in self.windows.values():
            w.ShowWindow(hwnd, 0)
        self.geometry = None
        if was_active:
            log.info("Overlay hidden")

    def close(self):
        self.hide()
        for hwnd in self.windows.values():
            w.DestroyWindow(hwnd)
        self.windows.clear()
        for name in reversed(self.registered):
            w.UnregisterClass(name, w.GetModuleHandle(None))
        self.registered.clear()
        log.info("Overlay resources released")
