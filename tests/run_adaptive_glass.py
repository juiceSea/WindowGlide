"""Opt-in desktop checks, only using a disposable fixture's solid color content."""

import ctypes as C
from ctypes import wintypes as W
import json
import re
import subprocess
import sys
import time

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor
from windowglide.window_manager import rect
from windowglide.overlay import GLASS_CLASS
from windowglide.glass import sample_glass, WHITE
from capture_fixture import capture


def run():
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None) or any(w.key_down(vk) for vk in (1, 2, 16, 17, 18)):
        raise RuntimeError("Stop WindowGlide and release input before running")
    point, foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(point))
    fixture = app = None
    blocker = None
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    results = []
    try:
        fixture = subprocess.Popen([sys.executable, str(ROOT / "tests/fixture_window.py")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", None), "fixture")
        w.SetWindowPos(hwnd, W.HWND(-1), 200, 160, 640, 440, 0x10)
        mouse(1, 420, 320)
        mouse(2)
        mouse(4)

        def paint(color):
            w.PostMessage(hwnd, 0x800C, color, 0)
            time.sleep(0.10)

        def begin():
            bounds = rect(hwnd)
            mouse(1, bounds[0] + 210, bounds[1] + 150)
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, bounds[0] + 235, bounds[1] + 175)
            glass = wait_for(lambda: w.FindWindow(GLASS_CLASS, None), "glass window")
            wait_for(lambda: w.IsWindowVisible(glass), "glass visible")
            time.sleep(0.08)

        def finish():
            mouse(4)
            key(w.VK_LMENU, True)
            wait_for(lambda: not w.IsWindowVisible(w.FindWindow(GLASS_CLASS, None)), "glass hidden")

        def verify(label, expected):
            bounds = rect(hwnd)
            width, height, pixels = capture(bounds, destination / f"adaptive-{label}.png")
            # Avoid the direction badge and window chrome.
            offset = ((height * 3 // 4) * width + width * 3 // 4) * 3
            actual = tuple(pixels[offset:offset + 3])
            assert all(abs(a - b) <= 3 for a, b in zip(actual, expected)), (label, actual, expected)
            results.append({label: actual})

        for adaptive in (True, False):
            config = destination / "adaptive-test-config.json"
            config.write_text(json.dumps({"adaptive_glass_color": adaptive}), encoding="utf-8")
            log = destination / ("adaptive-app.log" if adaptive else "fixed-white-app.log")
            with log.open("w", encoding="utf-8") as output:
                app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input",
                    "--config", str(config), "--smoke-seconds", "30"], stdout=output, stderr=output)
                wait_for(lambda: "READY" in log.read_text(encoding="utf-8"), "ready")
                paint(0xFFFFFF)
                begin()
                if adaptive:
                    verify("light-gray", (217, 218, 219))
                    # Content flips to black during the SAME drag. Color stays gray.
                    paint(0)
                    verify("locked-gray", (13, 14, 15))
                    finish()
                    begin()
                    verify("dark-white", (51, 51, 51))
                    finish()
                    paint(0xFFFFFF)
                    begin()
                    verify("light-again", (217, 218, 219))
                    finish()
                    text = log.read_text(encoding="utf-8")
                    assert text.count("Glass choice") == 3, text
                    times = [float(value) for value in re.findall(r"sample_ms=([0-9.]+)", text)]
                    results.append({"sample_ms": times, "samples_per_three_gestures": 3})
                    # Occlusion is rejected without asking another window to paint.
                    bounds = rect(hwnd)
                    blocker = w.check(w.CreateWindowEx(8 | 0x08000000, "BUTTON", "", 0x90000000,
                        bounds[0] + 270, bounds[1] + 180, 100, 100, None, None, w.GetModuleHandle(None), None),
                        "CreateWindowEx(occlusion fixture)")
                    choice = sample_glass(hwnd)
                    assert choice.color == WHITE and choice.reason == "content obscured or offscreen", choice
                    w.DestroyWindow(blocker)
                    blocker = None
                    results.append("occluded target falls back to white")
                else:
                    verify("disabled-white", (255, 255, 255))
                    finish()
                    assert "Glass choice" not in log.read_text(encoding="utf-8")
                    results.append("disabled adaptation uses fixed white without sampling")
                w.PostMessage(w.FindWindow(w.CLASS_NAME, None), w.WM_CLOSE, 0, 0)
                assert app.wait(timeout=5) == 0
                assert "ERROR" not in log.read_text(encoding="utf-8")
        (destination / "adaptive-glass.json").write_text(json.dumps({"passed": results}, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results}, indent=2))
    finally:
        mouse(4)
        key(w.VK_LMENU, True)
        if blocker:
            w.DestroyWindow(blocker)
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
