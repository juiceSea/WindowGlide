"""Opt-in check: disabled visuals create no windows and do not disable movement."""

import ctypes as C
from ctypes import wintypes as W
import json
import subprocess
import sys
import tempfile

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor
from windowglide.window_manager import rect
from windowglide.overlay import BORDER_CLASS, GLASS_CLASS
from windowglide.cursor import BADGE_CLASS


def run():
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None) or any(w.key_down(vk) for vk in (1, 2, 16, 17, 18)):
        raise RuntimeError("Stop WindowGlide and release input before running")
    point, foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(point))
    fixture = app = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            from pathlib import Path
            config = Path(directory) / "disabled.json"
            config.write_text(json.dumps(dict(enable_border=False, enable_glass=False,
                                              enable_cursor_change=False)), encoding="utf-8")
            fixture = subprocess.Popen([sys.executable, str(ROOT / "tests/fixture_window.py")],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", None), "fixture")
            w.SetWindowPos(hwnd, W.HWND(-1), 200, 160, 640, 440, 0x10)
            mouse(1, 420, 320)
            mouse(2)
            mouse(4)
            log = ROOT / "test-results/visual-disabled.log"
            with log.open("w", encoding="utf-8") as output:
                app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input",
                    "--config", str(config), "--smoke-seconds", "15"], stdout=output, stderr=output)
                wait_for(lambda: "READY" in log.read_text(encoding="utf-8"), "ready")
                before = rect(hwnd)
                mouse(1, before[0] + 220, before[1] + 160)
                assert w.GetAncestor(w.WindowFromPoint(W.POINT(before[0] + 220, before[1] + 160)), 2) == hwnd
                key(w.VK_LMENU)
                mouse(2)
                mouse(1, 460, 350)
                wait_for(lambda: rect(hwnd) != before, "movement with visuals disabled")
                assert not any(w.FindWindow(name, None) for name in (BORDER_CLASS, GLASS_CLASS, BADGE_CLASS))
                mouse(4)
                key(w.VK_LMENU, True)
                w.PostMessage(w.FindWindow(w.CLASS_NAME, None), w.WM_CLOSE, 0, 0)
                assert app.wait(timeout=5) == 0
                assert "ERROR" not in log.read_text(encoding="utf-8")
            print("PASS: visuals disabled by config; no feedback windows created; movement still works")
    finally:
        mouse(4)
        key(w.VK_LMENU, True)
        for process, name in ((app, w.CLASS_NAME), (fixture, "WindowGlide.AutomationFixture")):
            if process and process.poll() is None:
                hwnd = w.FindWindow(name, None)
                if hwnd:
                    w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
        set_cursor(point.x, point.y)
        if foreground and w.IsWindow(foreground):
            w.SetForegroundWindow(foreground)


if __name__ == "__main__":
    run()
