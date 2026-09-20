"""Small native drawing and cursor API surface; no system cursor replacement."""

import ctypes as C
from ctypes import wintypes as W
from . import win32 as w

gdi32 = C.WinDLL("gdi32", use_last_error=True)
CreateSolidBrush = w.bind(gdi32, "CreateSolidBrush", W.HBRUSH, W.DWORD)
DeleteObject = w.bind(gdi32, "DeleteObject", W.BOOL, W.HANDLE)
CreateRectRgn = w.bind(gdi32, "CreateRectRgn", W.HRGN, C.c_int, C.c_int, C.c_int, C.c_int)
CreateRoundRectRgn = w.bind(gdi32, "CreateRoundRectRgn", W.HRGN, *[C.c_int] * 6)
CombineRgn = w.bind(gdi32, "CombineRgn", C.c_int, W.HRGN, W.HRGN, W.HRGN, C.c_int)
SetWindowRgn = w.bind(w.user32, "SetWindowRgn", C.c_int, W.HWND, W.HRGN, W.BOOL)
SetLayeredWindowAttributes = w.bind(w.user32, "SetLayeredWindowAttributes", W.BOOL, W.HWND, W.DWORD, W.BYTE, W.DWORD)
GetWindow = w.bind(w.user32, "GetWindow", W.HWND, W.HWND, W.UINT)
SetClassLongPtr = w.bind(w.user32, "SetClassLongPtrW", C.c_size_t, W.HWND, C.c_int, C.c_ssize_t)
LoadCursor = w.bind(w.user32, "LoadCursorW", W.HANDLE, W.HINSTANCE, W.LPCWSTR)
SetWindowText = w.bind(w.user32, "SetWindowTextW", W.BOOL, W.HWND, W.LPCWSTR)
InvalidateRect = w.bind(w.user32, "InvalidateRect", W.BOOL, W.HWND, C.POINTER(W.RECT), W.BOOL)
FillRect = w.bind(w.user32, "FillRect", C.c_int, W.HDC, C.POINTER(W.RECT), W.HBRUSH)
DrawIconEx = w.bind(w.user32, "DrawIconEx", W.BOOL, W.HDC, C.c_int, C.c_int, W.HANDLE,
                   C.c_int, C.c_int, W.UINT, W.HBRUSH, W.UINT)


class PAINTSTRUCT(C.Structure):
    _fields_ = [("hdc", W.HDC), ("fErase", W.BOOL), ("rcPaint", W.RECT),
                ("fRestore", W.BOOL), ("fIncUpdate", W.BOOL), ("rgbReserved", W.BYTE * 32)]


BeginPaint = w.bind(w.user32, "BeginPaint", W.HDC, W.HWND, C.POINTER(PAINTSTRUCT))
EndPaint = w.bind(w.user32, "EndPaint", W.BOOL, W.HWND, C.POINTER(PAINTSTRUCT))


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class BLENDFUNCTION(C.Structure):
    _fields_ = [("BlendOp", W.BYTE), ("BlendFlags", W.BYTE),
                ("SourceConstantAlpha", W.BYTE), ("AlphaFormat", W.BYTE)]


CreateCompatibleDC = w.bind(gdi32, "CreateCompatibleDC", W.HDC, W.HDC)
DeleteDC = w.bind(gdi32, "DeleteDC", W.BOOL, W.HDC)
SelectObject = w.bind(gdi32, "SelectObject", W.HANDLE, W.HDC, W.HANDLE)
CreateDIBSection = w.bind(gdi32, "CreateDIBSection", W.HBITMAP, W.HDC, C.POINTER(BITMAPINFOHEADER),
                          W.UINT, C.POINTER(W.LPVOID), W.HANDLE, W.DWORD)
UpdateLayeredWindow = w.bind(w.user32, "UpdateLayeredWindow", W.BOOL, W.HWND, W.HDC,
    C.POINTER(W.POINT), C.POINTER(W.SIZE), W.HDC, C.POINTER(W.POINT), W.DWORD,
    C.POINTER(BLENDFUNCTION), W.DWORD)


def set_layered_pixels(hwnd, size, pixels):
    """Upload premultiplied BGRA once per art change; Windows keeps the surface."""
    memory = w.check(CreateCompatibleDC(None), "CreateCompatibleDC(badge)")
    bitmap = original = None
    try:
        info = BITMAPINFOHEADER(biSize=C.sizeof(BITMAPINFOHEADER), biWidth=size, biHeight=-size,
                               biPlanes=1, biBitCount=32)
        bits = W.LPVOID()
        bitmap = w.check(CreateDIBSection(memory, C.byref(info), 0, C.byref(bits), None, 0),
                         "CreateDIBSection(badge)")
        C.memmove(bits, pixels, len(pixels))
        original = w.check(SelectObject(memory, bitmap), "SelectObject(badge)")
        dimensions, origin = W.SIZE(size, size), W.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        w.check(UpdateLayeredWindow(hwnd, None, None, C.byref(dimensions), memory, C.byref(origin),
                                   0, C.byref(blend), 2), "UpdateLayeredWindow(badge)")
    finally:
        if original:
            SelectObject(memory, original)
        if bitmap:
            DeleteObject(bitmap)
        DeleteDC(memory)


class CURSORINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hCursor", W.HANDLE), ("ptScreenPos", W.POINT)]


GetCursorInfo = w.bind(w.user32, "GetCursorInfo", W.BOOL, C.POINTER(CURSORINFO))


def cursor_info():
    info = CURSORINFO(cbSize=C.sizeof(CURSORINFO))
    w.check(GetCursorInfo(C.byref(info)), "GetCursorInfo")
    return info


def system_cursor(resource_id):
    resource = C.cast(C.c_void_p(resource_id), W.LPCWSTR)
    return w.check(LoadCursor(None, resource), "LoadCursor")


def color_ref(value):
    red, green, blue = (int(value[start:start + 2], 16) for start in (1, 3, 5))
    return red | green << 8 | blue << 16
