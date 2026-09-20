"""Opt-in Win gesture checks on an owned fixture. Verifies the native plain-Win action.

Do not use the keyboard or mouse during this test. Restores pointer/focus on exit.
"""

import ctypes as C
import argparse
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


def run(shift_left=False):
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None) or any(w.key_down(vk) for vk in (1, 2, 16, 17, 18, 0x5B, 0x5C)):
        raise RuntimeError("Stop WindowGlide and release all buttons/modifiers first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    app = fixture = None
    results = []
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    label = "win-shift-left" if shift_left else "win"
    log = destination / f"{label}-app.log"
    try:
        # File output avoids a fixture pipe filling during the input matrix.
        with (destination / f"{label}-fixture.jsonl").open("w", encoding="utf-8") as events, log.open("w", encoding="utf-8") as output:
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
            config_args = gesture_config_arguments(label, "Win")
            config_path = destination / f"{label}-config.json"
            config_values = json.loads(config_path.read_text(encoding="utf-8"))
            config_values["enable_shift_left_resize"] = shift_left
            config_path.write_text(json.dumps(config_values), encoding="utf-8")
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "90"]
                                   + config_args, stdout=output, stderr=output)
            wait_for(lambda: "READY" in log.read_text(encoding="utf-8"), "Win app ready")

            def no_start():
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    assert w.GetForegroundWindow() == hwnd, ("Unexpected foreground after gesture", foreground_process())
                    time.sleep(0.01)
                assert not any(w.key_down(vk) for vk in (0x10, 0x5B, 0x5C, 0xE8)), "Latched modifier/mask key"
                assert app.poll() is None

            for vk in (0x5B, 0x5C):
                for button, down, up in (("move", 2, 4), ("resize", 8, 16)):
                    use_shift = shift_left and button == "resize"
                    if use_shift:
                        down, up = 2, 4
                    shift_vk = 0xA0 if vk == 0x5B else 0xA1
                    endings = ("mouse", "win", "escape", "click", "center") + (("shift", "double_tap") if use_shift else ())
                    for ending in endings:
                        w.SetWindowPos(hwnd, None, 200, 160, 640, 440, 0x4 | 0x10)
                        before = rect(hwnd)
                        x, y = (520, 380) if ending == "center" else (740, 510)
                        mouse(1, x, y)
                        wait_for(lambda: w.GetAncestor(w.WindowFromPoint(W.POINT(x, y)), 2) == hwnd,
                                 "fixture unobscured after shell transition")
                        key(vk)
                        if use_shift:
                            key(shift_vk)
                        if ending == "double_tap":
                            mouse(down)
                            mouse(up)
                            assert rect(hwnd) == before
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
                        elif ending == "shift":
                            key(shift_vk, True)
                            mouse(1, x + 60, y + 60)
                            assert rect(hwnd) == expected, "Shift release did not stop resize"
                        before_release = rect(hwnd)
                        mouse(up)
                        if use_shift and ending != "shift":
                            key(shift_vk, True)
                        if ending != "win":
                            key(vk, True)
                        no_start()
                        assert rect(hwnd) == before_release, "Geometry changed after release (possible snapping conflict)"
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
            events.flush()
            recorded = [json.loads(line) for line in (destination / f"{label}-fixture.jsonl").read_text(encoding="utf-8").splitlines()]
            assert not any(row.get("event") == "enter" for row in recorded), "Unexpected native move/resize loop"
            results.append("no native move/resize loop or post-release snapping observed")
            (destination / f"{label}-integration.json").write_text(json.dumps({"passed": results}, indent=2), encoding="utf-8")
            print(json.dumps({"passed": results}, indent=2))
    finally:
        mouse(4)
        mouse(16)
        for vk in (0xA0, 0xA1, 0x5B, 0x5C, w.VK_ESCAPE):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--shift-left", action="store_true")
    run(parser.parse_args().shift_left)
