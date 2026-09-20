"""Neutral Alt/Win menu-mask input; never suppress or replay a real release.

VK E8 is documented as unassigned by Microsoft and used as a menu mask by
AutoHotkey. Pairing down/up prevents a latched synthetic key. The private
marker keeps these events out of our own gesture recognition.
"""

import ctypes as C
from ctypes import wintypes as W

from . import win32 as w

MENU_MASK_VK = 0xE8
MENU_MASK_MARKER = 0x57474D4B


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
               ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", w.ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
               ("time", W.DWORD), ("dwExtraInfo", w.ULONG_PTR)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", INPUTUNION)]


send_input = w.bind(w.user32, "SendInput", W.UINT, W.UINT, C.POINTER(INPUT), C.c_int)


def mask_alt_menu():
    """Mask Alt's menu or Win's Start menu with the same neutral key pair."""
    events = (INPUT * 2)(
        INPUT(type=1, ki=KEYBDINPUT(wVk=MENU_MASK_VK, dwExtraInfo=MENU_MASK_MARKER)),
        INPUT(type=1, ki=KEYBDINPUT(wVk=MENU_MASK_VK, dwFlags=2, dwExtraInfo=MENU_MASK_MARKER)),
    )
    sent = send_input(2, events, C.sizeof(INPUT))
    if sent == 1:
        # Best-effort release if Windows accepted only the synthetic key-down.
        send_input(1, C.byref(events[1]), C.sizeof(INPUT))
    return sent == 2
