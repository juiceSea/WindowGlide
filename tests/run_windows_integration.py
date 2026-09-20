"""Opt-in live test: moves only a disposable test window using marked SendInput.

Run from project root: python tests/run_windows_integration.py
Do not touch the mouse/keyboard during this short test.
Ordinary WindowGlide runs ignore injected gestures.
"""

import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from windowglide import win32 as w
from windowglide.window_manager import rect


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
set_cursor = w.bind(w.user32, "SetCursorPos", W.BOOL, C.c_int, C.c_int)


def wait_for(predicate, label, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError(f"Timed out: {label}")


def key(vk, up=False):
    value = INPUT(type=1, ki=KEYBDINPUT(wVk=vk, dwFlags=2 if up else 0, dwExtraInfo=w.TEST_INPUT_MARKER))
    w.check(send_input(1, C.byref(value), C.sizeof(INPUT)), "SendInput(key)")
    time.sleep(0.04)


def mouse(flags, x=0, y=0):
    if flags & 1:
        vx, vy = w.GetSystemMetrics(76), w.GetSystemMetrics(77)
        width, height = w.GetSystemMetrics(78), w.GetSystemMetrics(79)
        x, y = round((x - vx) * 65535 / (width - 1)), round((y - vy) * 65535 / (height - 1))
        flags |= 0x8000 | 0x4000
    value = INPUT(type=0, mi=MOUSEINPUT(dx=x, dy=y, dwFlags=flags, dwExtraInfo=w.TEST_INPUT_MARKER))
    w.check(send_input(1, C.byref(value), C.sizeof(INPUT)), "SendInput(mouse)")
    time.sleep(0.05)


def run():
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None):
        raise RuntimeError("Stop the existing WindowGlide before running integration tests")
    if any(w.key_down(vk) for vk in (1, 2, 0x10, 0x11, 0x12, 0x5B, 0x5C)):
        raise RuntimeError("Release mouse buttons and modifier keys first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    results = []
    fixture = app = None
    log_file = ROOT / "test-results" / "integration-app.log"
    log_file.parent.mkdir(exist_ok=True)
    try:
        fixture = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fixture_window.py")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", None), "fixture window")
        w.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 1 | 2 | 0x10)
        mouse(1, 420, 320)
        assert w.GetAncestor(w.WindowFromPoint(W.POINT(420, 320)), 2) == hwnd
        mouse(2)
        mouse(4)
        w.SetForegroundWindow(hwnd)
        wait_for(lambda: w.GetForegroundWindow() == hwnd, "fixture foreground")
        with log_file.open("w", encoding="utf-8") as output:
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "45"],
                                   stdout=output, stderr=output)
            wait_for(lambda: "READY" in log_file.read_text(encoding="utf-8"), "application ready")

            def phase(number):
                w.PostMessage(hwnd, 0x800A, number, 0)
                time.sleep(0.04)

            phase(1)  # plain Alt must still reach the app and activate its menu logic
            key(w.VK_LMENU)
            key(w.VK_LMENU, True)
            assert not w.key_down(w.VK_MENU)
            phase(2)  # an ordinary Alt+D shortcut must not be remapped or masked
            key(w.VK_LMENU)
            key(ord("D"))
            key(ord("D"), True)
            key(w.VK_LMENU, True)
            phase(3)  # move, mouse released before Alt
            duplicate = subprocess.run([sys.executable, str(ROOT / "main.py")], capture_output=True, text=True, timeout=5)
            assert duplicate.returncode == 0 and "Already running" in duplicate.stderr, duplicate.stderr
            results.append("single instance rejected duplicate")

            before = rect(hwnd)
            x, y = before[0] + 220, before[1] + 160
            mouse(1, x, y)
            assert w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 12, y + 8)
            wait_for(lambda: rect(hwnd)[:2] == (before[0] + 12, before[1] + 8), "move started")
            for i in range(1, 7):
                mouse(1, x + 12 + 12 * i, y + 8 + 8 * i)
            moved = rect(hwnd)
            assert moved != before, ("window did not move", before, moved)
            mouse(4)
            wait_for(lambda: "reason=mouse released" in log_file.read_text(encoding="utf-8"), "move ended on mouse up")
            key(w.VK_LMENU, True)
            at_stop = rect(hwnd)
            mouse(1, x + 130, y + 100)
            time.sleep(0.12)
            assert rect(hwnd) == at_stop
            results.append({"mouse_release": {"before": before, "after": rect(hwnd)}})

            for stop in ("alt", "escape"):
                phase(4 if stop == "alt" else 5)
                w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
                before = rect(hwnd)
                x, y = before[0] + 220, before[1] + 160
                mouse(1, x, y)
                assert w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd
                key(w.VK_LMENU)
                mouse(2)
                mouse(1, x + 12, y + 8)
                wait_for(lambda: rect(hwnd)[:2] == (before[0] + 12, before[1] + 8), f"move start for {stop}")
                mouse(1, x + 65, y + 40)
                wait_for(lambda: rect(hwnd)[:2] == (before[0] + 65, before[1] + 40), "last position applied")
                at_stop = rect(hwnd)
                if stop == "alt":
                    key(w.VK_LMENU, True)
                else:
                    key(w.VK_ESCAPE)
                    key(w.VK_ESCAPE, True)
                wait_for(lambda: f"reason={stop}" in log_file.read_text(encoding="utf-8"), f"move end for {stop}")
                mouse(1, x + 100, y + 70)
                assert rect(hwnd) == at_stop, ("moved after stop or rolled back", stop, at_stop, rect(hwnd))
                mouse(4)
                if stop == "escape":
                    key(w.VK_LMENU, True)
                results.append(f"{stop} ends move and retains geometry")
                assert not w.key_down(w.VK_MENU) and not w.key_down(0xE8), "latched Alt/menu-mask key"

            phase(6)
            w.ShowWindow(hwnd, 3)
            wait_for(lambda: w.IsZoomed(hwnd), "maximize fixture")
            bounds = rect(hwnd)
            x, y = (bounds[0] + bounds[2]) // 2, bounds[1] + 180
            mouse(1, x, y)
            assert w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd
            key(w.VK_LMENU)
            mouse(2)
            mouse(4)
            assert w.IsZoomed(hwnd), "Alt-click without a drag restored maximized window"
            key(w.VK_LMENU, True)
            results.append("maximized Alt-click does not restore")
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 15, y + 15)
            wait_for(lambda: not w.IsZoomed(hwnd), "maximized drag restores window")
            mouse(1, x + 80, y + 50)
            mouse(4)
            key(w.VK_LMENU, True)
            time.sleep(0.12)
            results.append("maximized drag restores and moves")

            # Closing/minimizing during a held gesture must not leave controller state behind.
            w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
            before = rect(hwnd)
            x, y = before[0] + 220, before[1] + 160
            mouse(1, x, y)
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 20, y + 20)
            wait_for(lambda: rect(hwnd)[:2] == (before[0] + 20, before[1] + 20), "move before minimize")
            w.ShowWindow(hwnd, 6)
            wait_for(lambda: any(reason in log_file.read_text(encoding="utf-8") for reason in
                     ("reason=target closed or minimized", "reason=target closed, hidden or minimized")),
                     "minimized cleanup")
            mouse(4)
            key(w.VK_LMENU, True)
            w.ShowWindow(hwnd, 9)
            w.SetForegroundWindow(hwnd)
            results.append("target minimize clears active gesture")

            # The previous exit chord must no longer stop this instance.
            for vk in (0x11, w.VK_LMENU, 0x10, ord("Q")):
                key(vk)
            for vk in (ord("Q"), 0x10, w.VK_LMENU, 0x11):
                key(vk, True)
            time.sleep(0.15)
            assert app.poll() is None and w.FindWindow(w.CLASS_NAME, None)
            results.append("previous Ctrl+Alt+Shift+Q no longer exits")

            # Registered global exit chord, rather than just a posted WM_CLOSE.
            key(0x11)
            key(w.VK_LMENU)
            key(0x5B)
            key(ord("Q"))
            key(ord("Q"), True)
            key(0x5B, True)
            key(w.VK_LMENU, True)
            key(0x11, True)
            assert app.wait(timeout=5) == 0
            assert not w.FindWindow(w.CLASS_NAME, None)
            results.append("Ctrl+Win+Alt+Q exits and releases hooks")

            # Start a fresh instance, then exit while dragging.
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "30"],
                                   stdout=output, stderr=output)
            wait_for(lambda: log_file.read_text(encoding="utf-8").count("READY") == 2, "second instance ready")
            w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
            before = rect(hwnd)
            x, y = before[0] + 220, before[1] + 160
            mouse(1, x, y)
            assert w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd
            key(w.VK_LMENU)
            mouse(2)
            mouse(1, x + 20, y + 20)
            wait_for(lambda: rect(hwnd)[:2] == (before[0] + 20, before[1] + 20), "move before shutdown")

            stopped = subprocess.run([sys.executable, str(ROOT / "main.py"), "--stop"],
                                     capture_output=True, text=True, timeout=5)
            assert stopped.returncode == 0
            assert app.wait(timeout=5) == 0
            assert not w.FindWindow(w.CLASS_NAME, None)
            at_exit = rect(hwnd)
            mouse(1, x + 90, y + 60)
            time.sleep(0.12)
            assert rect(hwnd) == at_exit
            mouse(4)
            key(w.VK_LMENU, True)
            results.append("CLI stop during drag exits, releases hooks, and leaves position stable")
        report = {"passed": results, "fixture_events": None}
        w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
        out, err = fixture.communicate(timeout=5)
        assert fixture.returncode == 0 and not err, err
        report["fixture_events"] = [json.loads(line) for line in out.splitlines()]
        phases = {}
        current_phase = 0
        for event in report["fixture_events"]:
            if "phase" in event:
                current_phase = event["phase"]
            else:
                phases.setdefault(current_phase, []).append(event)
        def menu_events(number):
            return [event for event in phases[number] if event.get("message") == 0x112
                    and event.get("wp") == 0xF100 and event.get("lp") == 0]
        assert menu_events(1), "Plain Alt no longer reaches native menu handling"
        assert any(event.get("vk") == ord("D") and event.get("key_message") == w.WM_SYSKEYDOWN
                   for event in phases[2]), "Alt+D no longer reaches the application"
        assert not any(event.get("vk") == 0xE8 for number in (1, 2) for event in phases[number]), \
            "Plain Alt or Alt+D unexpectedly masked"
        for number in (3, 4, 5):
            assert not menu_events(number), f"Drag completion activated Alt menu (phase {number})"
            assert any(event.get("vk") == 0xE8 for event in phases[number]), f"Mask missing in phase {number}"
        results.append("Alt menu regression: plain Alt/Alt+D preserved; all three drag endings masked; no stuck keys")
        (ROOT / "test-results" / "integration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results, "fixture_event_count": len(report["fixture_events"])}, indent=2))
    finally:
        mouse(4)
        key(w.VK_ESCAPE, True)
        key(w.VK_LMENU, True)
        key(0x10, True)
        key(0x11, True)
        if app and app.poll() is None:
            control = w.FindWindow(w.CLASS_NAME, None)
            if control:
                w.PostMessage(control, w.WM_CLOSE, 0, 0)
            try:
                app.wait(timeout=5)
            except subprocess.TimeoutExpired:
                app.terminate()
                app.wait(timeout=5)
        if fixture and fixture.poll() is None:
            target = w.FindWindow("WindowGlide.AutomationFixture", None)
            if target:
                w.PostMessage(target, w.WM_CLOSE, 0, 0)
            try:
                fixture.wait(timeout=3)
            except subprocess.TimeoutExpired:
                fixture.terminate()
                fixture.wait(timeout=3)
        if fixture and fixture.stdout and not fixture.stdout.closed:
            out, err = fixture.communicate(timeout=3)
            (ROOT / "test-results" / "fixture-debug.log").write_text(out + err, encoding="utf-8")
        set_cursor(saved_point.x, saved_point.y)
        if saved_foreground and w.IsWindow(saved_foreground):
            w.SetForegroundWindow(saved_foreground)


if __name__ == "__main__":
    run()
