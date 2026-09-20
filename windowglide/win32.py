"""Explicit pointer-safe Win32 declarations. Windows 11, Python 3.11+."""

import ctypes as C
from ctypes import wintypes as W

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
advapi32 = C.WinDLL("advapi32", use_last_error=True)
dwmapi = C.WinDLL("dwmapi", use_last_error=True)
LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
ULONG_PTR = C.c_size_t
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, WPARAM, LPARAM)
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
WINEVENTPROC = C.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND,
                           W.LONG, W.LONG, W.DWORD, W.DWORD)


class MSLLHOOKSTRUCT(C.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KBDLLHOOKSTRUCT(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class WNDCLASS(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


class WINDOWPLACEMENT(C.Structure):
    _fields_ = [("length", W.UINT), ("flags", W.UINT), ("showCmd", W.UINT),
                ("ptMinPosition", W.POINT), ("ptMaxPosition", W.POINT),
                ("rcNormalPosition", W.RECT)]


class MONITORINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT),
                ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


class MINMAXINFO(C.Structure):
    _fields_ = [("ptReserved", W.POINT), ("ptMaxSize", W.POINT),
                ("ptMaxPosition", W.POINT), ("ptMinTrackSize", W.POINT), ("ptMaxTrackSize", W.POINT)]


class GUITHREADINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD),
                ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND),
                ("rcCaret", W.RECT)]


class SID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [("Sid", W.LPVOID), ("Attributes", W.DWORD)]


def bind(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, argtypes
    return fn


GetModuleHandle = bind(kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
GetCurrentThreadId = bind(kernel32, "GetCurrentThreadId", W.DWORD)
GetCurrentProcess = bind(kernel32, "GetCurrentProcess", W.HANDLE)
GetCurrentProcessId = bind(kernel32, "GetCurrentProcessId", W.DWORD)
CreateMutex = bind(kernel32, "CreateMutexW", W.HANDLE, W.LPVOID, W.BOOL, W.LPCWSTR)
CloseHandle = bind(kernel32, "CloseHandle", W.BOOL, W.HANDLE)
OpenProcess = bind(kernel32, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
QueryFullProcessImageName = bind(kernel32, "QueryFullProcessImageNameW", W.BOOL,
                                 W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))
OpenProcessToken = bind(advapi32, "OpenProcessToken", W.BOOL, W.HANDLE,
                        W.DWORD, C.POINTER(W.HANDLE))
GetTokenInformation = bind(advapi32, "GetTokenInformation", W.BOOL, W.HANDLE,
                           C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD))
GetSidSubAuthorityCount = bind(advapi32, "GetSidSubAuthorityCount", C.POINTER(W.BYTE), W.LPVOID)
GetSidSubAuthority = bind(advapi32, "GetSidSubAuthority", C.POINTER(W.DWORD), W.LPVOID, W.DWORD)
SetProcessDpiAwarenessContext = bind(user32, "SetProcessDpiAwarenessContext", W.BOOL, W.HANDLE)
GetThreadDpiAwarenessContext = bind(user32, "GetThreadDpiAwarenessContext", W.HANDLE)
AreDpiAwarenessContextsEqual = bind(user32, "AreDpiAwarenessContextsEqual", W.BOOL, W.HANDLE, W.HANDLE)
SetWindowsHookEx = bind(user32, "SetWindowsHookExW", W.HANDLE, C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
UnhookWindowsHookEx = bind(user32, "UnhookWindowsHookEx", W.BOOL, W.HANDLE)
CallNextHookEx = bind(user32, "CallNextHookEx", LRESULT, W.HANDLE, C.c_int, WPARAM, LPARAM)
GetAsyncKeyState = bind(user32, "GetAsyncKeyState", C.c_short, C.c_int)
GetMessage = bind(user32, "GetMessageW", W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
PeekMessage = bind(user32, "PeekMessageW", W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)
TranslateMessage = bind(user32, "TranslateMessage", W.BOOL, C.POINTER(W.MSG))
DispatchMessage = bind(user32, "DispatchMessageW", LRESULT, C.POINTER(W.MSG))
PostThreadMessage = bind(user32, "PostThreadMessageW", W.BOOL, W.DWORD, W.UINT, WPARAM, LPARAM)
PostMessage = bind(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, WPARAM, LPARAM)
SendMessageTimeout = bind(user32, "SendMessageTimeoutW", LRESULT, W.HWND, W.UINT, WPARAM,
                          LPARAM, W.UINT, W.UINT, C.POINTER(ULONG_PTR))
PostQuitMessage = bind(user32, "PostQuitMessage", None, C.c_int)
RegisterClass = bind(user32, "RegisterClassW", W.ATOM, C.POINTER(WNDCLASS))
UnregisterClass = bind(user32, "UnregisterClassW", W.BOOL, W.LPCWSTR, W.HINSTANCE)
CreateWindowEx = bind(user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR,
                      W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
DestroyWindow = bind(user32, "DestroyWindow", W.BOOL, W.HWND)
DefWindowProc = bind(user32, "DefWindowProcW", LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
FindWindow = bind(user32, "FindWindowW", W.HWND, W.LPCWSTR, W.LPCWSTR)
RegisterHotKey = bind(user32, "RegisterHotKey", W.BOOL, W.HWND, C.c_int, W.UINT, W.UINT)
UnregisterHotKey = bind(user32, "UnregisterHotKey", W.BOOL, W.HWND, C.c_int)
SetTimer = bind(user32, "SetTimer", ULONG_PTR, W.HWND, ULONG_PTR, W.UINT, W.LPVOID)
KillTimer = bind(user32, "KillTimer", W.BOOL, W.HWND, ULONG_PTR)
WindowFromPoint = bind(user32, "WindowFromPoint", W.HWND, W.POINT)
GetAncestor = bind(user32, "GetAncestor", W.HWND, W.HWND, W.UINT)
GetWindowLongPtr = bind(user32, "GetWindowLongPtrW", LONG_PTR := C.c_ssize_t, W.HWND, C.c_int)
GetClassName = bind(user32, "GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
GetWindowText = bind(user32, "GetWindowTextW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
GetWindowThreadProcessId = bind(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
GetWindowRect = bind(user32, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
GetWindowPlacement = bind(user32, "GetWindowPlacement", W.BOOL, W.HWND, C.POINTER(WINDOWPLACEMENT))
SetWindowPlacement = bind(user32, "SetWindowPlacement", W.BOOL, W.HWND, C.POINTER(WINDOWPLACEMENT))
SetWindowPos = bind(user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
ShowWindow = bind(user32, "ShowWindow", W.BOOL, W.HWND, C.c_int)
ShowWindowAsync = bind(user32, "ShowWindowAsync", W.BOOL, W.HWND, C.c_int)
GetTopWindow = bind(user32, "GetTopWindow", W.HWND, W.HWND)
GetWindow = bind(user32, "GetWindow", W.HWND, W.HWND, W.UINT)
SetForegroundWindow = bind(user32, "SetForegroundWindow", W.BOOL, W.HWND)
GetForegroundWindow = bind(user32, "GetForegroundWindow", W.HWND)
GetGUIThreadInfo = bind(user32, "GetGUIThreadInfo", W.BOOL, W.DWORD, C.POINTER(GUITHREADINFO))
GetCursorPos = bind(user32, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
ScreenToClient = bind(user32, "ScreenToClient", W.BOOL, W.HWND, C.POINTER(W.POINT))
GetSystemMetrics = bind(user32, "GetSystemMetrics", C.c_int, C.c_int)
GetSystemMetricsForDpi = bind(user32, "GetSystemMetricsForDpi", C.c_int, C.c_int, W.UINT)
MonitorFromWindow = bind(user32, "MonitorFromWindow", W.HMONITOR, W.HWND, W.DWORD)
MonitorFromPoint = bind(user32, "MonitorFromPoint", W.HMONITOR, W.POINT, W.DWORD)
GetMonitorInfo = bind(user32, "GetMonitorInfoW", W.BOOL, W.HMONITOR, C.POINTER(MONITORINFO))
GetDpiForWindow = bind(user32, "GetDpiForWindow", W.UINT, W.HWND)
for _name in ("IsWindow", "IsWindowVisible", "IsWindowEnabled", "IsIconic", "IsZoomed", "IsHungAppWindow"):
    globals()[_name] = bind(user32, _name, W.BOOL, W.HWND)
GetShellWindow = bind(user32, "GetShellWindow", W.HWND)
GetDesktopWindow = bind(user32, "GetDesktopWindow", W.HWND)
DwmGetWindowAttribute = bind(dwmapi, "DwmGetWindowAttribute", W.LONG, W.HWND, W.DWORD, W.LPVOID, W.DWORD)
SetWinEventHook = bind(user32, "SetWinEventHook", W.HANDLE, W.DWORD, W.DWORD, W.HMODULE,
                       WINEVENTPROC, W.DWORD, W.DWORD, W.DWORD)
UnhookWinEvent = bind(user32, "UnhookWinEvent", W.BOOL, W.HANDLE)

WM_CLOSE, WM_DESTROY, WM_TIMER, WM_HOTKEY = 0x10, 2, 0x113, 0x312
WM_QUIT, WM_APP_ACTION, WM_APP_RESET = 0x12, 0x8001, 0x8002
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_NCLBUTTONDOWN, WM_CANCELMODE = 0xA1, 0x1F
VK_MENU, VK_LMENU, VK_RMENU, VK_ESCAPE, VK_LBUTTON = 0x12, 0xA4, 0xA5, 0x1B, 1
WS_CAPTION, WS_THICKFRAME, WS_CHILD = 0x00C00000, 0x00040000, 0x40000000
CLASS_NAME = "WindowGlide.Control.0.1"
MUTEX_NAME = "Local\\WindowGlide.Singleton.0.1"
# Only accepted by explicit --test-input runs; ordinary injected events pass through.
TEST_INPUT_MARKER = 0x57474C44


def check(value, operation):
    if not value:
        raise OSError(C.get_last_error(), f"{operation}: {C.FormatError(C.get_last_error())}")
    return value


def dpi_awareness():
    if not SetProcessDpiAwarenessContext(W.HANDLE(-4)):
        if not AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), W.HANDLE(-4)):
            check(False, "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)")


def key_down(vk):
    return bool(GetAsyncKeyState(vk) & 0x8000)
