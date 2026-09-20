"""Opt-in Win gesture checks on an owned fixture. Verifies the native plain-Win action.

Do not use the keyboard or mouse during this test. Restores pointer/focus on exit.
"""

import ctypes as C
from ctypes import wintypes as W
import json
import subprocess
import sys
import time

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor, gesture_config_arguments
from windowglide.window_manager import rect


def foreground_process():
    pid = W.DWORD()
    w.GetWindowThreadProcessId(w.GetForegroundWindow(), C.byref(pid))
    handle = w.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        query = w.bind(w.kernel32, "QueryFullProcessImageNameW", W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))
        buffer, length = C.create_unicode_buffer(32768), W.DWORD(32768)
        w.check(query(handle, 0, buffer, C.byref(length)), "foreground executable")
        return buffer.value
    finally:
        w.CloseHandle(handle)


def run():
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None) or any(w.key_down(vk) for vk in (1, 2, 16, 17, 18, 0x5B, 0x5C)):
        raise RuntimeError("Stop WindowGlide and release all buttons/modifiers first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    app = fixture = None
    results = []
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    log = destination / "win-app.log"
    try:
        # File output avoids a fixture pipe filling during the input matrix.
        with (destination / "win-fixture.jsonl").open("w", encoding="utf-8") as events, log.open("w", encoding="utf-8") as output:
            fixture = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fixture_window.py")], stdout=events, stderr=events)
            hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", None), "fixture")
            w.SetWindowPos(hwnd, W.HWND(-1), 200, 160, 640, 440, 0x10)
            mouse(1, 420, 320)
            mouse(2)
            mouse(4)
            w.SetForegroundWindow(hwnd)
            wait_for(lambda: w.GetForegroundWindow() == hwnd, "fixture foreground")
            key(0x5B)
            key(0x5B, True)
            native_process = wait_for(lambda: foreground_process() if w.GetForegroundWindow() != hwnd else None,
                                      "native Win action before installing hooks")
            assert native_process.lower().endswith(("startmenuexperiencehost.exe", "searchhost.exe")), native_process
            time.sleep(0.4)  # wait for the shell's opening animation before Escape
            key(w.VK_ESCAPE)
            key(w.VK_ESCAPE, True)
            w.SetForegroundWindow(hwnd)
            wait_for(lambda: w.GetForegroundWindow() == hwnd, "native Win UI dismissed")
            results.append(f"Native plain Win baseline: {native_process}")
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "90"]
                                   + gesture_config_arguments("win", "Win"), stdout=output, stderr=output)
            wait_for(lambda: "READY" in log.read_text(encoding="utf-8"), "Win app ready")

            def no_start():
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    assert w.GetForegroundWindow() == hwnd, ("Unexpected foreground after gesture", foreground_process())
                    time.sleep(0.01)
                assert not any(w.key_down(vk) for vk in (0x5B, 0x5C, 0xE8)), "Latched Win/mask key"
                assert app.poll() is None

            for vk in (0x5B, 0x5C):
                for button, down, up in (("move", 2, 4), ("resize", 8, 16)):
                    for ending in ("mouse", "win", "escape", "click", "center"):
                        w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
                        before = rect(hwnd)
                        x, y = (520, 380) if ending == "center" else (740, 510)
                        mouse(1, x, y)
                        wait_for(lambda: w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd,
                                 "fixture unobscured after shell transition")
                        key(vk)
                        mouse(down)
                        if ending != "click":
                            mouse(1, x + 40, y + 30)
                            expected = ((240, 190, 880, 630) if button == "move" else
                                        before if ending == "center" else (200, 160, 880, 630))
                            wait_for(lambda: rect(hwnd) == expected, f"{button} {ending} geometry")
                            time.sleep(0.25)  # cross the controller's watchdog interval
                            mouse(1, x + 50, y + 40)
                            expected = ((250, 200, 890, 640) if button == "move" else
                                        before if ending == "center" else (200, 160, 890, 640))
                            wait_for(lambda: rect(hwnd) == expected, f"{button} survives watchdog")
                        else:
                            assert rect(hwnd) == before
                        if ending == "win":
                            key(vk, True)
                        elif ending == "escape":
                            key(w.VK_ESCAPE)
                            key(w.VK_ESCAPE, True)
                        mouse(up)
                        if ending != "win":
                            key(vk, True)
                        no_start()
                        stopped = rect(hwnd)
                        mouse(1, x + 60, y + 60)
                        assert rect(hwnd) == stopped
                        results.append(f"{hex(vk)} {button} {ending}: geometry stable, no Start, no stuck key")

                # Preserve this machine's native Win action (Start or Search).
                key(vk)
                key(vk, True)
                wait_for(lambda: foreground_process() == native_process, "plain Win retains native action")
                time.sleep(0.4)
                key(w.VK_ESCAPE)
                key(w.VK_ESCAPE, True)
                w.SetForegroundWindow(hwnd)
                wait_for(lambda: w.GetForegroundWindow() == hwnd, "Start dismissed")
                results.append(f"{hex(vk)} plain press after gestures retains native action")

            assert "mask was not fully delivered" not in log.read_text(encoding="utf-8")
            (destination / "win-integration.json").write_text(json.dumps({"passed": results}, indent=2), encoding="utf-8")
            print(json.dumps({"passed": results}, indent=2))
    finally:
        mouse(4)
        mouse(16)
        for vk in (0x5B, 0x5C, w.VK_ESCAPE):
            key(vk, True)
        for process, class_name in ((app, w.CLASS_NAME), (fixture, "WindowGlide.AutomationFixture")):
            if process and process.poll() is None:
                hwnd = w.FindWindow(class_name, None)
                if hwnd:
                    w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        set_cursor(saved_point.x, saved_point.y)
        if saved_foreground and w.IsWindow(saved_foreground):
            w.SetForegroundWindow(saved_foreground)


if __name__ == "__main__":
    run()
