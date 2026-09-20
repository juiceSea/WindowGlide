"""Opt-in Phase 2 desktop test. Operates only on the disposable fixture."""

import json
import subprocess
import sys
import time
import ctypes as C
from ctypes import wintypes as W

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor, gesture_config_arguments
from windowglide.window_manager import rect, visible_rect, tracking_limits


def run():
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None):
        raise RuntimeError("Stop WindowGlide before running the resize integration test")
    if any(w.key_down(vk) for vk in (1, 2, 0x10, 0x11, 0x12)):
        raise RuntimeError("Release mouse buttons and modifiers first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    app = fixture = None
    results = []
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    log_file = destination / "resize-app.log"
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
        with log_file.open("w", encoding="utf-8") as output:
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "60"] + gesture_config_arguments("resize"),
                                   stdout=output, stderr=output)
            wait_for(lambda: "READY" in log_file.read_text(encoding="utf-8"), "application ready")

            def phase(number):
                w.PostMessage(hwnd, 0x800A, number, 0)
                time.sleep(0.03)

            def reset(mode=0):
                w.PostMessage(hwnd, 0x800B, mode, 0)
                w.ShowWindow(hwnd, 9)
                w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
                time.sleep(0.05)
                return rect(hwnd)

            def start(x, y):
                mouse(1, x, y)
                assert w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd
                key(w.VK_LMENU)
                mouse(8)

            def finish():
                mouse(16)
                key(w.VK_LMENU, True)
                assert not w.key_down(w.VK_MENU) and not w.key_down(0xE8)

            phase(1)
            mouse(8)
            mouse(16)
            results.append("ordinary right click preserved")

            points = {"NW": (100, 90), "N": (320, 90), "NE": (540, 90), "W": (100, 220),
                      "E": (540, 220), "SW": (100, 350), "S": (320, 350), "SE": (540, 350)}
            for number, (direction, point) in enumerate(points.items(), 10):
                before = reset()
                phase(number)
                x, y = before[0] + point[0], before[1] + point[1]
                start(x, y)
                mouse(1, x + 48, y + 32)
                expected = tuple(value + delta for value, delta in zip(before,
                                 (48 if "W" in direction else 0, 32 if "N" in direction else 0,
                                  48 if "E" in direction else 0, 32 if "S" in direction else 0)))
                wait_for(lambda: rect(hwnd) == expected, f"{direction} geometry expected={expected} actual={rect(hwnd)}")
                finish()
                mouse(1, x + 80, y + 60)
                assert rect(hwnd) == expected
                results.append(f"{direction} resize keeps opposite edges fixed")

            for number, (delta, expected_width) in enumerate(((-120, 600), (120, 700)), 30):
                before = reset(1)
                phase(number)
                x, y = before[0] + 540, before[1] + 220
                start(x, y)
                mouse(1, x + delta, y)
                wait_for(lambda: rect(hwnd)[2] - rect(hwnd)[0] == expected_width, "application tracking limit")
                finish()
            results.append("application WM_GETMINMAXINFO minimum and maximum widths respected")

            for number, ending in enumerate(("alt", "escape"), 40):
                before = reset()
                phase(number)
                x, y = before[0] + 540, before[1] + 350
                start(x, y)
                mouse(1, x + 40, y + 30)
                expected = (before[0], before[1], before[2] + 40, before[3] + 30)
                wait_for(lambda: rect(hwnd) == expected, f"resize before {ending}")
                if ending == "alt":
                    key(w.VK_LMENU, True)
                else:
                    key(w.VK_ESCAPE)
                    key(w.VK_ESCAPE, True)
                mouse(1, x + 80, y + 60)
                assert rect(hwnd) == expected, (ending, rect(hwnd), expected)
                mouse(16)
                if ending == "escape":
                    key(w.VK_LMENU, True)
                results.append(f"{ending} stops resize and preserves result")

            reset()
            phase(50)
            w.ShowWindow(hwnd, 3)
            wait_for(lambda: w.IsZoomed(hwnd), "maximized fixture")
            before = visible_rect(hwnd)
            x, y = before[0] + (before[2] - before[0]) // 6, (before[1] + before[3]) // 2
            start(x, y)
            mouse(16)
            key(w.VK_LMENU, True)
            assert w.IsZoomed(hwnd), "right click without drag restored maximized window"
            phase(51)
            start(x, y)
            mouse(1, x + 60, y)
            wait_for(lambda: not w.IsZoomed(hwnd), "maximized resize exits maximized mode")
            wanted_visible = (before[0] + 60, before[1], before[2], before[3])
            wait_for(lambda: all(abs(a - b) <= 1 for a, b in zip(visible_rect(hwnd), wanted_visible)),
                     f"maximized resize visible edges expected={wanted_visible} actual={visible_rect(hwnd)}")
            finish()
            results.append("maximized west resize preserves all other visible edges; click alone does not restore")

            # User regression: keep Alt held across several gestures, expand a restored
            # maximized window to max tracking width, then move and resize it again.
            reset()
            phase(52)
            w.ShowWindow(hwnd, 3)
            wait_for(lambda: w.IsZoomed(hwnd), "maximize for continuous-Alt regression")
            before = visible_rect(hwnd)
            x, y = before[0] + (before[2] - before[0]) * 5 // 6, (before[1] + before[3]) // 2
            start(x, y)
            mouse(1, x - 200, y)
            wait_for(lambda: not w.IsZoomed(hwnd) and visible_rect(hwnd)[2] < before[2] - 100, "shrink maximized right edge")
            mouse(16)  # Alt remains held.
            shrunk = rect(hwnd)
            x, y = shrunk[0] + (shrunk[2] - shrunk[0]) * 5 // 6, (shrunk[1] + shrunk[3]) // 2
            mouse(1, x, y)
            mouse(8)
            maximum_width = tracking_limits(hwnd).max_width
            delta = maximum_width - (shrunk[2] - shrunk[0]) + 20
            mouse(1, x + delta, y)
            wait_for(lambda: rect(hwnd)[2] - rect(hwnd)[0] == maximum_width, "expand to application maximum width")
            mouse(16)
            expanded = rect(hwnd)
            x, y = expanded[0] + 400, expanded[1] + 180
            mouse(1, x, y)
            mouse(2)
            mouse(1, x + 35, y + 25)
            wait_for(lambda: rect(hwnd)[:2] == (expanded[0] + 35, expanded[1] + 25), "move still works after maximum-size expansion")
            mouse(4)
            moved = rect(hwnd)
            x, y = moved[0] + (moved[2] - moved[0]) * 5 // 6, moved[1] + 220
            mouse(1, x, y)
            mouse(8)
            mouse(1, x - 60, y)
            wait_for(lambda: rect(hwnd)[2] == moved[2] - 60, "resize still works after maximum-size expansion")
            finish()
            results.append("continuous Alt: maximize, shrink right, expand to maximum, then move and resize again")

            before = reset(2)
            phase(60)
            start(before[0] + 540, before[1] + 220)
            mouse(1, before[0] + 580, before[1] + 250)
            finish()
            assert rect(hwnd) == before, "fixed-size window resized"
            results.append("fixed-size window skipped; right-click passes through")

            for phase_number, drag in ((70, False), (71, True)):
                before = reset()
                phase(phase_number)
                x, y = (before[0] + before[2]) // 2, (before[1] + before[3]) // 2
                start(x, y)
                if drag:
                    mouse(1, x + 240, y + 140)  # Cross well outside the center.
                finish()
                assert rect(hwnd) == before, "center right gesture changed geometry"
            results.append("center right click and drag-out keep geometry and consume menus")

            reset()
            phase(72)
            w.ShowWindow(hwnd, 3)
            wait_for(lambda: w.IsZoomed(hwnd), "maximize for inactive center")
            before = rect(hwnd)
            x, y = (before[0] + before[2]) // 2, (before[1] + before[3]) // 2
            start(x, y)
            mouse(1, x + 300, y + 150)
            finish()
            assert w.IsZoomed(hwnd) and rect(hwnd) == before, "center right drag restored maximized window"
            results.append("maximized center right drag does not restore or resize")

            before = reset()
            phase(73)
            x, y = (before[0] + before[2]) // 2, (before[1] + before[3]) // 2
            mouse(1, x, y)
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 35, y + 25)
            try:
                wait_for(lambda: rect(hwnd)[:2] == (before[0] + 35, before[1] + 25), "center left drag still moves")
            except AssertionError as exc:
                raise AssertionError(f"center move before={before} after={rect(hwnd)} zoomed={w.IsZoomed(hwnd)}") from exc
            mouse(4)
            key(w.VK_LMENU, True)
            results.append("center left drag still moves normally")

            subprocess.run([sys.executable, str(ROOT / "main.py"), "--stop"], check=True, capture_output=True, timeout=5)
            assert app.wait(timeout=5) == 0
        w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
        out, err = fixture.communicate(timeout=5)
        assert not err and fixture.returncode == 0, err
        events = [json.loads(line) for line in out.splitlines()]
        phases, current = {}, 0
        for event in events:
            if "phase" in event:
                current = event["phase"]
            else:
                phases.setdefault(current, []).append(event)
        assert any(event.get("context_menu") for event in phases[1]), "normal right-click was suppressed"
        assert any(event.get("context_menu") for event in phases[60]), "fixed-size right-click was suppressed"
        drag_phases = list(range(10, 18)) + [30, 31, 40, 41, 51, 52, 70, 71, 72, 73]
        for number in drag_phases:
            assert not any(event.get("context_menu") for event in phases[number]), f"right-menu leak in phase {number}"
            assert not any(event.get("message") == 0x112 and event.get("wp") == 0xF100 and event.get("lp") == 0
                           for event in phases[number]), f"Alt-menu leak in phase {number}"
        results.append("no right context menu or Alt menu after resize gestures")
        report = {"passed": results, "fixture_events": events}
        (destination / "resize.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results, "fixture_event_count": len(events)}, indent=2))
    finally:
        mouse(16)
        mouse(4)
        key(w.VK_ESCAPE, True)
        key(w.VK_LMENU, True)
        for process, name in ((app, w.CLASS_NAME), (fixture, "WindowGlide.AutomationFixture")):
            if process and process.poll() is None:
                window = w.FindWindow(name, None)
                if window:
                    w.PostMessage(window, w.WM_CLOSE, 0, 0)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
        if fixture and fixture.stdout and not fixture.stdout.closed:
            out, err = fixture.communicate(timeout=3)
            (destination / "resize-fixture-debug.log").write_text(out + err, encoding="utf-8")
        set_cursor(saved_point.x, saved_point.y)
        if saved_foreground and w.IsWindow(saved_foreground):
            w.SetForegroundWindow(saved_foreground)


if __name__ == "__main__":
    run()
