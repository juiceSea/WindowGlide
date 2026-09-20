"""Opt-in native visual checks on a disposable fixture; restores pointer on completion."""

import ctypes as C
import argparse
from ctypes import wintypes as W
import json
import subprocess
import sys
import time

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor
from windowglide.window_manager import rect, visible_rect
from windowglide import visual_win32 as v
from windowglide.overlay import BORDER_CLASS, GLASS_CLASS
from windowglide.cursor import BADGE_CLASS
from windowglide.accent import read_windows_accent
from windowglide.config import load_config
from capture_fixture import capture


def run(overlays_only=False, theme=False):
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None):
        raise RuntimeError("Stop WindowGlide before visual integration tests")
    if any(w.key_down(vk) for vk in (1, 2, 0x10, 0x11, 0x12)):
        raise RuntimeError("Release mouse buttons and modifier keys first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    app = fixture = None
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    app_log = destination / "visual-app.log"
    results = []
    extra_arguments = []
    expected_color = (124, 155, 197)
    expected_width = load_config(ROOT / "config.json").border_width
    if theme:
        theme_config = destination / "theme-config.json"
        theme_config.write_text(json.dumps({"use_windows_accent_color": True}), encoding="utf-8")
        extra_arguments = ["--config", str(theme_config)]
        expected_width = 3
        accent = read_windows_accent()
        expected_color = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    def check_cursor(direction, label):
        if not overlays_only:
            def matches():
                title = C.create_unicode_buffer(32)
                w.GetWindowText(badge, title, 32)
                return w.IsWindowVisible(badge) and title.value == direction
            wait_for(matches, label)
            assert v.cursor_info().hCursor == v.system_cursor(32512), "real pointer was changed"
    try:
        fixture = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fixture_window.py")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", None), "fixture")
        w.SetWindowPos(hwnd, W.HWND(-1), 200, 160, 640, 440, 0x10)
        mouse(1, 420, 320)
        assert w.GetAncestor(w.WindowFromPoint(W.POINT(420, 320)), 2) == hwnd
        mouse(2)
        mouse(4)
        w.SetForegroundWindow(hwnd)
        wait_for(lambda: w.GetForegroundWindow() == hwnd, "fixture foreground")
        with app_log.open("w", encoding="utf-8") as output:
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "45"] + extra_arguments,
                                   stdout=output, stderr=output)
            wait_for(lambda: "READY" in app_log.read_text(encoding="utf-8"), "ready")
            border = w.FindWindow(BORDER_CLASS, None)
            glass = w.FindWindow(GLASS_CLASS, None)
            badge = w.FindWindow(BADGE_CLASS, None)
            assert border and glass and badge
            assert not w.IsWindowVisible(badge)
            assert not w.IsWindowVisible(border) and not w.IsWindowVisible(glass)
            for overlay in (border, glass, badge):
                style = w.GetWindowLongPtr(overlay, -20)
                required = 0x80000 | 0x20 | 0x80 | 0x08000000
                assert style & required == required and not style & 0x40000, hex(style)
            results.append("overlays hidden at idle; layered, click-through, tool-window and no-activate styles set")

            before = rect(hwnd)
            x, y = before[0] + 220, before[1] + 180
            mouse(1, x, y)
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 40, y + 25)
            wait_for(lambda: w.IsWindowVisible(border) and w.IsWindowVisible(glass), "visuals visible")
            wait_for(lambda: rect(glass) == visible_rect(hwnd), "glass matches target visible bounds")
            assert w.GetForegroundWindow() == hwnd, "overlay stole focus"
            check_cursor("move", "move direction badge")
            for step in range(1, 5):
                mouse(1, x + 40 + step * 10, y + 25 + step * 5)
                wait_for(lambda: rect(glass) == visible_rect(hwnd), "overlay follows movement")
                check_cursor("move", "direction badge survives target cursor reset")
                if not overlays_only:
                    wait_for(lambda: rect(badge)[0] == x + 60 + step * 10, "badge follows pointer")
            assert v.GetWindow(border, 2) == glass and v.GetWindow(glass, 2) == hwnd
            results.append("move border/glass follow actual target bounds, preserve focus and sit immediately above target")
            if not overlays_only:
                results.append("direction badge follows pointer while real cursor stays unchanged")
            mouse(0x20)
            mouse(0x40)
            time.sleep(0.12)
            b = rect(border)
            width, height, pixels = capture(b, destination / ("theme-preview.png" if theme else "overlay-preview.png"))
            color = tuple(pixels[(width // 2) * 3:(width // 2) * 3 + 3])
            assert color == expected_color, ("border color", color, expected_color)
            visible = visible_rect(hwnd)
            border_width = round(expected_width * (w.GetDpiForWindow(hwnd) or 96) / 96)
            assert tuple(visible[i] - b[i] for i in (0, 1)) == (border_width, border_width)
            assert tuple(b[i] - visible[i] for i in (2, 3)) == (border_width, border_width)
            index = ((height // 2) * width + width // 2) * 3
            glass_color = tuple(pixels[index:index + 3])
            assert all(abs(actual - wanted) <= 3 for actual, wanted in zip(glass_color, (77, 102, 128))), glass_color
            results.append({"visible_pixel_check": {"border_rgb": color, "tinted_client_rgb": glass_color}})
            if not overlays_only:
                capture(rect(badge), destination / "direction-preview.png")
            mouse(4)
            key(w.VK_LMENU, True)
            wait_for(lambda: not w.IsWindowVisible(border) and not w.IsWindowVisible(glass), "visuals hidden after release")
            assert not w.IsWindowVisible(badge)
            mouse(1, 430, 330)
            wait_for(lambda: v.cursor_info().hCursor == v.system_cursor(32512), "normal cursor restored")
            results.append("release hides both overlays and restores normal cursor")

            # All direction badge families, including opposite diagonal orientations.
            for direction, offset, resource in (("E", (540, 220), 32644), ("N", (320, 90), 32645),
                                                 ("SE", (540, 350), 32642), ("NE", (540, 90), 32643)):
                w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
                mouse(1, 200 + offset[0], 160 + offset[1])
                key(w.VK_LMENU)
                mouse(8)
                mouse(1, 220 + offset[0], 175 + offset[1])
                wait_for(lambda: w.IsWindowVisible(glass), f"{direction} glass")
                wait_for(lambda: rect(glass) == visible_rect(hwnd), f"{direction} glass geometry")
                check_cursor(direction, f"{direction} direction badge")
                if not overlays_only:
                    time.sleep(0.06)
                    capture(rect(badge), destination / f"direction-{direction}.png")
                key(w.VK_ESCAPE)
                key(w.VK_ESCAPE, True)
                wait_for(lambda: not w.IsWindowVisible(glass), "Esc clears overlay")
                assert not w.IsWindowVisible(badge)
                mouse(16)
                key(w.VK_LMENU, True)
            results.append("resize overlays follow all four direction families; Esc clears them")

            w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
            mouse(1, 520, 380)
            key(w.VK_LMENU)
            mouse(8)
            mouse(1, 700, 460)
            assert not w.IsWindowVisible(glass) and not w.IsWindowVisible(border) and not w.IsWindowVisible(badge)
            mouse(16)
            key(w.VK_LMENU, True)
            results.append("inactive center has no active-operation overlay")

            w.SetWindowPos(hwnd, W.HWND(-2), 200, 160, 640, 440, 0x10)
            mouse(1, 420, 320)
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, 445, 340)
            wait_for(lambda: w.IsWindowVisible(glass), "overlay before target close")
            assert not w.GetWindowLongPtr(border, -20) & 8 and not w.GetWindowLongPtr(glass, -20) & 8
            assert w.GetForegroundWindow() == hwnd
            results.append("overlays follow target back to ordinary non-topmost band without changing focus")
            w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
            wait_for(lambda: not w.IsWindowVisible(glass) and not w.IsWindowVisible(border), "target destruction clears overlay")
            assert not w.IsWindowVisible(badge)
            mouse(4)
            key(w.VK_LMENU, True)
            out, err = fixture.communicate(timeout=5)
            assert fixture.returncode == 0 and not err, err
            events = [json.loads(line) for line in out.splitlines()]
            assert any(event.get("middle_mouse") == 0x207 for event in events)
            assert any(event.get("middle_mouse") == 0x208 for event in events)
            results.append("middle-button input reaches underlying target through overlays")
            results.append("closing target clears overlays")
            subprocess.run([sys.executable, str(ROOT / "main.py"), "--stop"], check=True, capture_output=True, timeout=5)
            assert app.wait(timeout=5) == 0
            assert not w.FindWindow(BORDER_CLASS, None) and not w.FindWindow(GLASS_CLASS, None)
            assert not w.FindWindow(BADGE_CLASS, None)
            assert "ERROR" not in app_log.read_text(encoding="utf-8")
            results.append("shutdown destroys overlay windows without runtime errors")
        report = {"passed": results, "cursor_checks_skipped": overlays_only, "windows_accent_enabled": theme}
        report_name = "visual-theme.json" if theme else ("overlay-only.json" if overlays_only else "visual.json")
        (destination / report_name).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results}, indent=2))
    finally:
        mouse(4)
        mouse(16)
        key(w.VK_ESCAPE, True)
        key(w.VK_LMENU, True)
        for process, class_name in ((app, w.CLASS_NAME), (fixture, "WindowGlide.AutomationFixture")):
            if process and process.poll() is None:
                target = w.FindWindow(class_name, None)
                if target:
                    w.PostMessage(target, w.WM_CLOSE, 0, 0)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
        set_cursor(saved_point.x, saved_point.y)
        if saved_foreground and w.IsWindow(saved_foreground):
            w.SetForegroundWindow(saved_foreground)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlays-only", action="store_true", help="Explicitly skip pending operation-cursor checks")
    parser.add_argument("--theme", action="store_true", help="Check Windows accent using a separate test config")
    args = parser.parse_args()
    run(args.overlays_only, args.theme)
