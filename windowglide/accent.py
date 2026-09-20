"""Read the user's Windows accent via UISettings; no registry writes or polling."""

import ctypes as C
from ctypes import wintypes as W
import logging
from uuid import UUID

from . import win32 as w

log = logging.getLogger(__name__)
runtime = C.WinDLL("combase")
RoInitialize = w.bind(runtime, "RoInitialize", W.LONG, W.UINT)
RoUninitialize = w.bind(runtime, "RoUninitialize", None)
WindowsCreateString = w.bind(runtime, "WindowsCreateString", W.LONG, W.LPCWSTR, W.UINT, C.POINTER(C.c_void_p))
WindowsDeleteString = w.bind(runtime, "WindowsDeleteString", W.LONG, C.c_void_p)
RoActivateInstance = w.bind(runtime, "RoActivateInstance", W.LONG, C.c_void_p, C.POINTER(C.c_void_p))


class Color(C.Structure):
    _fields_ = [(name, W.BYTE) for name in ("A", "R", "G", "B")]


def check_hr(result, operation):
    if result < 0:
        raise OSError(f"{operation} failed (HRESULT 0x{result & 0xFFFFFFFF:08X})")


def method(instance, slot, restype, *arguments):
    table = C.cast(instance, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(restype, C.c_void_p, *arguments)(table[slot])


def read_windows_accent():
    # Balance successful initialization, but respect an existing different apartment.
    status = RoInitialize(0)
    if status < 0 and status != -2147417850:  # RPC_E_CHANGED_MODE
        check_hr(status, "RoInitialize")
    name = C.c_void_p()
    instance = C.c_void_p()
    settings = C.c_void_p()
    try:
        class_name = "Windows.UI.ViewManagement.UISettings"
        check_hr(WindowsCreateString(class_name, len(class_name), C.byref(name)), "WindowsCreateString")
        check_hr(RoActivateInstance(name, C.byref(instance)), "RoActivateInstance(UISettings)")
        iid = (C.c_ubyte * 16).from_buffer_copy(UUID("03021be4-5254-4781-8194-5168f7d06d7b").bytes_le)
        query = method(instance, 0, W.LONG, C.c_void_p, C.POINTER(C.c_void_p))
        check_hr(query(instance, C.byref(iid), C.byref(settings)), "QueryInterface(IUISettings3)")
        color = Color()
        # IInspectable has six slots; GetColorValue is the first IUISettings3 method.
        get_color = method(settings, 6, W.LONG, C.c_int, C.POINTER(Color))
        check_hr(get_color(settings, 5, C.byref(color)), "UISettings.GetColorValue(Accent)")
        return f"#{color.R:02X}{color.G:02X}{color.B:02X}"
    finally:
        for pointer in (settings, instance):
            if pointer:
                method(pointer, 2, W.ULONG)(pointer)
        if name:
            WindowsDeleteString(name)
        if status >= 0:
            RoUninitialize()


class BorderColor:
    def __init__(self, settings):
        self.settings = settings
        self.failed = False

    def resolve(self):
        if not self.settings.use_windows_accent_color:
            return self.settings.border_color
        try:
            color = read_windows_accent()
        except OSError as exc:
            if not self.failed:
                log.warning("Windows accent unavailable; using configured border color %s: %s",
                            self.settings.border_color, exc)
            self.failed = True
            return self.settings.border_color
        if self.failed:
            log.info("Windows accent color reading recovered")
        self.failed = False
        return color
