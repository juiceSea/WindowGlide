"""Capture a bounded fixture region to PNG using Win32 and standard-library PNG encoding."""

import ctypes as C
from ctypes import wintypes as W
import struct
import zlib

from windowglide import win32 as w
from windowglide import visual_win32 as v

get_dc = w.bind(w.user32, "GetDC", W.HDC, W.HWND)
release_dc = w.bind(w.user32, "ReleaseDC", C.c_int, W.HWND, W.HDC)
create_dc = w.bind(v.gdi32, "CreateCompatibleDC", W.HDC, W.HDC)
delete_dc = w.bind(v.gdi32, "DeleteDC", W.BOOL, W.HDC)
create_bitmap = w.bind(v.gdi32, "CreateCompatibleBitmap", W.HBITMAP, W.HDC, C.c_int, C.c_int)
select_object = w.bind(v.gdi32, "SelectObject", W.HANDLE, W.HDC, W.HANDLE)
bit_blt = w.bind(v.gdi32, "BitBlt", W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                 W.HDC, C.c_int, C.c_int, W.DWORD)


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


get_bits = w.bind(v.gdi32, "GetDIBits", C.c_int, W.HDC, W.HBITMAP, W.UINT, W.UINT,
                  W.LPVOID, C.POINTER(BITMAPINFOHEADER), W.UINT)


def capture(bounds, path):
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    screen = w.check(get_dc(None), "GetDC(capture)")
    memory = bitmap = original = None
    try:
        memory = w.check(create_dc(screen), "CreateCompatibleDC")
        bitmap = w.check(create_bitmap(screen, width, height), "CreateCompatibleBitmap")
        original = select_object(memory, bitmap)
        w.check(bit_blt(memory, 0, 0, width, height, screen, left, top, 0x40CC0020), "BitBlt(capture)")
        select_object(memory, original)
        original = None
        info = BITMAPINFOHEADER(biSize=C.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height,
                                biPlanes=1, biBitCount=32)
        buffer = C.create_string_buffer(width * height * 4)
        w.check(get_bits(screen, bitmap, 0, height, buffer, C.byref(info), 0), "GetDIBits")
        raw = buffer.raw
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
        scanlines = b"".join(b"\0" + rgb[row * width * 3:(row + 1) * width * 3] for row in range(height))

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))
        return width, height, rgb
    finally:
        if original:
            select_object(memory, original)
        if bitmap:
            v.DeleteObject(bitmap)
        if memory:
            delete_dc(memory)
        release_dc(None, screen)
