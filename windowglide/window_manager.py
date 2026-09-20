"""Target policy and coalesced, event-driven window positioning."""

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import logging
from pathlib import PureWindowsPath

from . import win32 as w
from .geometry import moved_origin, restored_origin
from .resize import SizeLimits, direction_at, resized_rect

log = logging.getLogger(__name__)
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "DV2ControlHost", "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
                 "MultitaskingViewFrame", "#32768", "tooltips_class32"}
SHELL_PROCESSES = {"startmenuexperiencehost.exe", "shellexperiencehost.exe", "searchhost.exe",
                   "searchapp.exe", "lockapp.exe", "textinputhost.exe", "sihost.exe"}


def window_class(hwnd):
    text = C.create_unicode_buffer(256)
    w.GetClassName(hwnd, text, len(text))
    return text.value


def candidate_at(x, y, resizing=False):
    """Only bounded USER32 queries here: called once on button-down in the hook."""
    child = w.WindowFromPoint(W.POINT(x, y))
    hwnd = w.GetAncestor(child, 2) if child else None
    if not hwnd or hwnd in (w.GetDesktopWindow(), w.GetShellWindow()):
        return None
    if not w.IsWindowVisible(hwnd) or not w.IsWindowEnabled(hwnd) or w.IsIconic(hwnd):
        return None
    style = w.GetWindowLongPtr(hwnd, -16)
    if style & w.WS_CHILD or not style & (w.WS_CAPTION | w.WS_THICKFRAME):
        return None
    if resizing and not style & w.WS_THICKFRAME:
        return None
    if window_class(hwnd) in SHELL_CLASSES:
        return None
    pid = W.DWORD()
    w.GetWindowThreadProcessId(hwnd, C.byref(pid))
    if pid.value == w.GetCurrentProcessId():
        return None
    return hwnd


def integrity(process):
    token = W.HANDLE()
    w.check(w.OpenProcessToken(process, 8, C.byref(token)), "OpenProcessToken")
    try:
        needed = W.DWORD()
        w.GetTokenInformation(token, 25, None, 0, C.byref(needed))
        if not needed.value:
            w.check(False, "GetTokenInformation(size)")
        buffer = C.create_string_buffer(needed.value)
        w.check(w.GetTokenInformation(token, 25, buffer, needed, C.byref(needed)), "GetTokenInformation")
        sid = C.cast(buffer, C.POINTER(w.SID_AND_ATTRIBUTES)).contents.Sid
        count = w.GetSidSubAuthorityCount(sid)[0]
        return w.GetSidSubAuthority(sid, count - 1)[0]
    finally:
        w.CloseHandle(token)


def rect(hwnd):
    value = W.RECT()
    w.check(w.GetWindowRect(hwnd, C.byref(value)), "GetWindowRect")
    return value.left, value.top, value.right, value.bottom


def monitor_info(hwnd):
    info = w.MONITORINFO(cbSize=C.sizeof(w.MONITORINFO))
    w.check(w.GetMonitorInfo(w.MonitorFromWindow(hwnd, 2), C.byref(info)), "GetMonitorInfo")
    return info


def visible_rect(hwnd):
    value = W.RECT()
    if w.DwmGetWindowAttribute(hwnd, 9, C.byref(value), C.sizeof(value)) == 0:
        return value.left, value.top, value.right, value.bottom
    return rect(hwnd)


def is_borderless_fullscreen(hwnd):
    # A normal decorated window may cover or exceed a monitor after resizing.
    # Size alone is not evidence that the application entered fullscreen mode.
    style = w.GetWindowLongPtr(hwnd, -16)
    if w.IsZoomed(hwnd) or style & w.WS_CAPTION == w.WS_CAPTION:
        return False
    left, top, right, bottom = visible_rect(hwnd)
    monitor = monitor_info(hwnd).rcMonitor
    return left <= monitor.left and top <= monitor.top and right >= monitor.right and bottom >= monitor.bottom


def restore_at(hwnd, bounds):
    placement = w.WINDOWPLACEMENT(length=C.sizeof(w.WINDOWPLACEMENT))
    w.check(w.GetWindowPlacement(hwnd, C.byref(placement)), "GetWindowPlacement")
    info = monitor_info(hwnd)
    offset_x = offset_y = 0
    if not w.GetWindowLongPtr(hwnd, -20) & 0x80:
        offset_x = info.rcWork.left - info.rcMonitor.left
        offset_y = info.rcWork.top - info.rcMonitor.top
    left, top, right, bottom = bounds
    placement.rcNormalPosition = W.RECT(left - offset_x, top - offset_y, right - offset_x, bottom - offset_y)
    placement.showCmd, placement.flags = 1, 4
    w.check(w.SetWindowPlacement(hwnd, C.byref(placement)), "SetWindowPlacement(restore at bounds)")


def tracking_limits(hwnd):
    dpi = w.GetDpiForWindow(hwnd) or 96
    value = w.MINMAXINFO()
    value.ptMinTrackSize = W.POINT(max(1, w.GetSystemMetricsForDpi(34, dpi)),
                                   max(1, w.GetSystemMetricsForDpi(35, dpi)))
    value.ptMaxTrackSize = W.POINT(max(value.ptMinTrackSize.x, w.GetSystemMetrics(59)),
                                   max(value.ptMinTrackSize.y, w.GetSystemMetrics(60)))
    value.ptMaxSize = W.POINT(w.GetSystemMetrics(61), w.GetSystemMetrics(62))
    value.ptMaxPosition = W.POINT(-w.GetSystemMetricsForDpi(32, dpi), -w.GetSystemMetricsForDpi(33, dpi))
    result = w.ULONG_PTR()
    C.set_last_error(0)
    # System message marshalling copies MINMAXINFO across process boundaries.
    # The controller waits at most 150ms; the independent input hook never waits.
    w.check(w.SendMessageTimeout(hwnd, 0x24, 0, C.addressof(value), 0x23, 150, C.byref(result)),
            "WM_GETMINMAXINFO (failed or timed out; resize skipped)")
    return SizeLimits(max(1, value.ptMinTrackSize.x), max(1, value.ptMinTrackSize.y),
                      max(1, value.ptMaxTrackSize.x), max(1, value.ptMaxTrackSize.y))


def restored_bounds_for_maximized_resize(hwnd):
    """Preserve DWM-visible edges when changing back to the normal frame."""
    left, top, right, bottom = visible_rect(hwnd)
    dpi = w.GetDpiForWindow(hwnd) or 96
    border = W.UINT()
    if w.DwmGetWindowAttribute(hwnd, 37, C.byref(border), C.sizeof(border)) != 0:
        border.value = w.GetSystemMetricsForDpi(5, dpi)
    pad = w.GetSystemMetricsForDpi(92, dpi)
    side = max(0, w.GetSystemMetricsForDpi(32, dpi) + pad - border.value)
    lower = max(0, w.GetSystemMetricsForDpi(33, dpi) + pad - border.value)
    return left - side, top, right + side, bottom + lower


@dataclass
class Target:
    hwnd: int
    pid: int
    tid: int
    title: str

    def alive(self):
        pid = W.DWORD()
        tid = w.GetWindowThreadProcessId(self.hwnd, C.byref(pid))
        return tid == self.tid and pid.value == self.pid and bool(w.IsWindow(self.hwnd))


@dataclass
class Movement:
    initial_rect: tuple[int, int, int, int]
    initial_point: tuple[int, int]
    last_position: tuple[int, int] | None = None


@dataclass
class Resizing:
    initial_rect: tuple[int, int, int, int]
    initial_point: tuple[int, int]
    direction: str
    limits: SizeLimits
    last_rect: tuple[int, int, int, int] | None = None


class WindowManager:
    def __init__(self):
        self.own_integrity = integrity(w.GetCurrentProcess())

    def inspect(self, hwnd):
        if not w.IsWindow(hwnd) or not w.IsWindowEnabled(hwnd) or w.IsHungAppWindow(hwnd):
            raise ValueError("Target is gone, disabled or unresponsive")
        cloaked = W.DWORD()
        if w.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked)) == 0 and cloaked.value:
            raise ValueError("Target is cloaked")
        pid = W.DWORD()
        tid = w.GetWindowThreadProcessId(hwnd, C.byref(pid))
        process = w.check(w.OpenProcess(0x1000, False, pid.value), "OpenProcess(query)")
        try:
            if integrity(process) > self.own_integrity:
                raise PermissionError("Higher-integrity target; no UIPI bypass")
            path = C.create_unicode_buffer(32768)
            size = W.DWORD(len(path))
            w.check(w.QueryFullProcessImageName(process, 0, path, C.byref(size)), "QueryFullProcessImageName")
            if PureWindowsPath(path.value).name.lower() in SHELL_PROCESSES:
                raise ValueError("System shell UI is excluded")
        finally:
            w.CloseHandle(process)
        if is_borderless_fullscreen(hwnd):
            raise ValueError("Fullscreen window is excluded")
        title = C.create_unicode_buffer(512)
        w.GetWindowText(hwnd, title, len(title))
        return Target(hwnd, pid.value, tid, title.value.replace("\n", " ").replace("\r", " "))

    def begin_move(self, target, origin, current):
        if not target.alive() or w.IsHungAppWindow(target.hwnd):
            raise ValueError("Target became unavailable")
        hwnd = target.hwnd
        # Foreground policy is honored; no AttachThreadInput or focus-lock bypass.
        if not w.SetForegroundWindow(hwnd) and w.GetForegroundWindow() != hwnd:
            log.info("Foreground activation denied; moving without stealing focus hwnd=0x%X", hwnd)
        bounds = rect(hwnd)
        start = origin
        if w.IsZoomed(hwnd):
            placement = w.WINDOWPLACEMENT(length=C.sizeof(w.WINDOWPLACEMENT))
            w.check(w.GetWindowPlacement(hwnd, C.byref(placement)), "GetWindowPlacement")
            normal = placement.rcNormalPosition
            width, height = normal.right - normal.left, normal.bottom - normal.top
            info = monitor_info(hwnd)
            work = info.rcWork
            dpi = w.GetDpiForWindow(hwnd) or 96
            x, y = restored_origin(current, bounds, (width, height),
                                    (work.left, work.top, work.right, work.bottom), round(32 * dpi / 96))
            if width <= 0 or height <= 0:
                raise ValueError("Invalid normal window size")
            # WINDOWPLACEMENT uses workspace coordinates except for tool windows.
            offset_x = offset_y = 0
            if not w.GetWindowLongPtr(hwnd, -20) & 0x80:
                offset_x = work.left - info.rcMonitor.left
                offset_y = work.top - info.rcMonitor.top
            placement.rcNormalPosition = W.RECT(x - offset_x, y - offset_y,
                                               x - offset_x + width, y - offset_y + height)
            # Restore directly at the anchored position. Do not flash at the old location.
            placement.showCmd, placement.flags = 1, 4  # WPF_ASYNCWINDOWPLACEMENT
            w.check(w.SetWindowPlacement(hwnd, C.byref(placement)), "SetWindowPlacement(restore)")
            bounds = (x, y, x + width, y + height)
            start = current
        movement = Movement(bounds, start)
        self.update_move(target, movement, current)
        log.info("Move started hwnd=0x%X pid=%s title=%r backend=event-driven", hwnd, target.pid, target.title)
        return movement

    def update_move(self, target, movement, point):
        if not target.alive() or w.IsIconic(target.hwnd):
            raise ValueError("Target closed or minimized")
        x, y = moved_origin(movement.initial_rect, movement.initial_point, point)
        if movement.last_position == (x, y):
            return
        # ASYNCWINDOWPOS prevents an unresponsive foreign UI from blocking this controller.
        flags = 0x4000 | 0x0010 | 0x0004 | 0x0001  # async, no activate, no Z change, no size
        w.check(w.SetWindowPos(target.hwnd, None, x, y, 0, 0, flags), "SetWindowPos(move)")
        movement.last_position = (x, y)

    def begin_resize(self, target, origin, current):
        hwnd = target.hwnd
        if not target.alive() or w.IsHungAppWindow(hwnd) or not w.GetWindowLongPtr(hwnd, -16) & w.WS_THICKFRAME:
            raise ValueError("Target is unavailable or does not support resizing")
        direction = direction_at(visible_rect(hwnd), origin)
        if direction is None:
            # This gesture remains consumed until release, even after crossing out
            # of the center. Do not activate, restore, resize, or query size limits.
            log.info("Resize center reserved hwnd=0x%X title=%r; no geometry change", hwnd, target.title)
            return None
        limits = tracking_limits(hwnd)
        w.SetForegroundWindow(hwnd)  # Respect foreground restrictions just like moving.
        if w.IsZoomed(hwnd):
            bounds = restored_bounds_for_maximized_resize(hwnd)
            operation = Resizing(bounds, origin, direction, limits)
            wanted = resized_rect(bounds, origin, current, direction, limits)
            restore_at(hwnd, wanted)
            operation.last_rect = wanted
        else:
            operation = Resizing(rect(hwnd), origin, direction, limits)
            self.update_resize(target, operation, current)
        log.info("Resize started hwnd=0x%X pid=%s title=%r direction=%s limits=%s",
                 hwnd, target.pid, target.title, direction, limits)
        return operation

    def update_resize(self, target, operation, point):
        if not target.alive() or w.IsIconic(target.hwnd):
            raise ValueError("Target closed or minimized")
        wanted = resized_rect(operation.initial_rect, operation.initial_point, point,
                              operation.direction, operation.limits)
        if wanted == operation.last_rect:
            return
        left, top, right, bottom = wanted
        w.check(w.SetWindowPos(target.hwnd, None, left, top, right - left, bottom - top,
                               0x4000 | 0x0010 | 0x0004), "SetWindowPos(resize)")
        operation.last_rect = wanted

    def update_position(self, target, operation, point):
        if isinstance(operation, Resizing):
            self.update_resize(target, operation, point)
        else:
            self.update_move(target, operation, point)
