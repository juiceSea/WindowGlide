"""Disposable native test window, launched only by the integration runner."""

import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windowglide import win32 as w
from windowglide import visual_win32 as v

w.dpi_awareness()
limited_size = False
set_style = w.bind(w.user32, "SetWindowLongPtrW", C.c_ssize_t, W.HWND, C.c_int, C.c_ssize_t)


@w.WNDPROC
def procedure(hwnd, message, wp, lp):
    global limited_size
    if message == 0x800C:
        brush = v.CreateSolidBrush(wp)
        previous = v.SetClassLongPtr(hwnd, -10, brush)
        v.DeleteObject(previous)
        v.InvalidateRect(hwnd, None, True)
        return 0
    if message == 0x800B:
        limited_size = wp == 1
        style = w.GetWindowLongPtr(hwnd, -16)
        set_style(hwnd, -16, style & ~w.WS_THICKFRAME if wp == 2 else style | w.WS_THICKFRAME)
        return 0
    if message == 0x24 and limited_size:
        info = C.cast(lp, C.POINTER(w.MINMAXINFO)).contents
        info.ptMinTrackSize = W.POINT(600, 400)
        info.ptMaxTrackSize = W.POINT(700, 480)
        return 0
    if message == 0x7B:
        print(json.dumps({"context_menu": True}), flush=True)
    if message in (0x207, 0x208):
        print(json.dumps({"middle_mouse": message}), flush=True)
    if message == 0x800A:
        print(json.dumps({"phase": wp}), flush=True)
        return 0
    if message in (w.WM_KEYDOWN, w.WM_KEYUP, w.WM_SYSKEYDOWN, w.WM_SYSKEYUP):
        print(json.dumps({"key_message": message, "vk": wp}), flush=True)
    if message in (0x112, 0xA1):
        print(json.dumps({"message": message, "wp": wp, "lp": lp, "left_down": w.key_down(1)}), flush=True)
    if message in (0x231, 0x232):
        print(json.dumps({"event": "enter" if message == 0x231 else "exit"}), flush=True)
    elif message == w.WM_DESTROY:
        w.PostQuitMessage(0)
        return 0
    return w.DefWindowProc(hwnd, message, wp, lp)


instance = w.GetModuleHandle(None)
name = "WindowGlide.AutomationFixture"
wc = w.WNDCLASS(lpfnWndProc=procedure, hInstance=instance, lpszClassName=name,
                hbrBackground=v.CreateSolidBrush(0x604020), hCursor=v.system_cursor(32512))
w.check(w.RegisterClass(C.byref(wc)), "RegisterClass(fixture)")
title = sys.argv[1] if len(sys.argv) > 1 else "WindowGlide disposable integration test"
hwnd = w.check(w.CreateWindowEx(0, name, title, 0x10CF0000,
                               200, 160, 640, 440, None, None, instance, None), "CreateWindowEx(fixture)")
print(json.dumps({"hwnd": hwnd}), flush=True)
msg = W.MSG()
while w.GetMessage(C.byref(msg), None, 0, 0) > 0:
    w.TranslateMessage(C.byref(msg))
    w.DispatchMessage(C.byref(msg))
w.UnregisterClass(name, instance)
