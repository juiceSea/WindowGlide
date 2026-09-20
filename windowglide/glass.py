"""One small in-memory sample before movement and before our overlays appear."""

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import time

from . import win32 as w
from . import visual_win32 as v

WHITE = "#FFFFFF"
GRAY = "#40444B"
SIDE = 24
GetClientRect = w.bind(w.user32, "GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
ClientToScreen = w.bind(w.user32, "ClientToScreen", W.BOOL, W.HWND, C.POINTER(W.POINT))
GetDC = w.bind(w.user32, "GetDC", W.HDC, W.HWND)
ReleaseDC = w.bind(w.user32, "ReleaseDC", C.c_int, W.HWND, W.HDC)
StretchBlt = w.bind(v.gdi32, "StretchBlt", W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                    W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.DWORD)
SetStretchBltMode = w.bind(v.gdi32, "SetStretchBltMode", C.c_int, W.HDC, C.c_int)
SetBrushOrgEx = w.bind(v.gdi32, "SetBrushOrgEx", W.BOOL, W.HDC, C.c_int, C.c_int, C.POINTER(W.POINT))
GdiFlush = w.bind(v.gdi32, "GdiFlush", W.BOOL)


@dataclass(frozen=True)
class GlassChoice:
    color: str = WHITE
    reason: str = "unavailable"
    brightness: float | None = None
    elapsed_ms: float = 0


def classify(pixels):
    """Mean display luma, not application theme; mixed content is approximate."""
    if not pixels or len(pixels) % 4:
        return GlassChoice(reason="invalid pixels")
    brightness = sum(0.2126 * pixels[i + 2] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i]
                     for i in range(0, len(pixels), 4)) / (len(pixels) // 4 * 255)
    return GlassChoice(GRAY if brightness >= 0.60 else WHITE, "sampled", brightness)


def sample_glass(hwnd):
    started = time.perf_counter()
    screen = memory = bitmap = original = None
    try:
        if not w.IsWindowVisible(hwnd) or w.IsIconic(hwnd):
            return GlassChoice(reason="target unavailable")
        client = W.RECT()
        w.check(GetClientRect(hwnd, C.byref(client)), "GetClientRect(glass)")
        origin = W.POINT(client.left, client.top)
        w.check(ClientToScreen(hwnd, C.byref(origin)), "ClientToScreen(glass)")
        # Trim edges/toolbars; only sample the window's visible content interior.
        width, height = client.right - client.left, client.bottom - client.top
        left, top = origin.x + width // 10, origin.y + height // 10
        width, height = width * 8 // 10, height * 8 // 10
        if width < SIDE or height < SIDE:
            return GlassChoice(reason="content too small")
        points = [(left + width * x // 6, top + height * y // 6) for y in range(1, 6) for x in range(1, 6)]
        # Fail closed if another visible window covers sampled locations. No
        # activation, cross-process WM_PRINT, screenshot file, or image logging.
        if any(w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) != hwnd for x, y in points):
            return GlassChoice(reason="content obscured or offscreen")
        screen = w.check(GetDC(None), "GetDC(glass sample)")
        memory = w.check(v.CreateCompatibleDC(screen), "CreateCompatibleDC(glass sample)")
        info = v.BITMAPINFOHEADER(biSize=C.sizeof(v.BITMAPINFOHEADER), biWidth=SIDE, biHeight=-SIDE,
                                 biPlanes=1, biBitCount=32)
        bits = W.LPVOID()
        bitmap = w.check(v.CreateDIBSection(memory, C.byref(info), 0, C.byref(bits), None, 0),
                         "CreateDIBSection(glass sample)")
        original = w.check(v.SelectObject(memory, bitmap), "SelectObject(glass sample)")
        SetStretchBltMode(memory, 4)  # HALFTONE downsampling.
        SetBrushOrgEx(memory, 0, 0, None)
        w.check(StretchBlt(memory, 0, 0, SIDE, SIDE, screen, left, top, width, height, 0x00CC0020),
                "StretchBlt(glass sample)")
        w.check(GdiFlush(), "GdiFlush(glass sample)")
        result = classify(C.string_at(bits, SIDE * SIDE * 4))
        elapsed = (time.perf_counter() - started) * 1000
        return GlassChoice(result.color, result.reason, result.brightness, elapsed)
    except OSError:
        return GlassChoice(reason="sample failed", elapsed_ms=(time.perf_counter() - started) * 1000)
    finally:
        if original:
            v.SelectObject(memory, original)
        if bitmap:
            v.DeleteObject(bitmap)
        if memory:
            v.DeleteDC(memory)
        if screen:
            ReleaseDC(None, screen)
