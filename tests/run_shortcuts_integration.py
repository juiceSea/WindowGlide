"""Opt-in real Win32 shortcut checks; all manipulated windows are owned fixtures."""

import ctypes as C
import argparse
from ctypes import wintypes as W
import json
import subprocess
import sys
import time

from run_windows_integration import ROOT, w, wait_for, mouse, key, set_cursor, gesture_config_arguments, INPUT, KEYBDINPUT, send_input
from windowglide.window_manager import rect
from windowglide.overlay import GLASS_CLASS


def run(modifier="Alt"):
    w.dpi_awareness()
    if w.FindWindow(w.CLASS_NAME, None) or any(w.key_down(vk) for vk in (1, 2, 16, 17, 18, 0x5B, 0x5C)):
        raise RuntimeError("Stop WindowGlide and release mouse/modifier keys first")
    saved_point, saved_foreground = W.POINT(), w.GetForegroundWindow()
    w.GetCursorPos(C.byref(saved_point))
    destination = ROOT / "test-results"
    destination.mkdir(exist_ok=True)
    fixtures, outputs, handles = [], [], []
    app = None
    competitor = False
    results = []
    log = destination / "shortcuts-app.log"
    try:
        for index, name in enumerate(("A", "B", "C")):
            title = f"WindowGlide shortcut fixture {name}"
            path = destination / f"shortcut-fixture-{name}.jsonl"
            output = path.open("w", encoding="utf-8")
            outputs.append(output)
            process = subprocess.Popen([sys.executable, str(ROOT / "tests/fixture_window.py"), title], stdout=output, stderr=output)
            fixtures.append(process)
            hwnd = wait_for(lambda: w.FindWindow("WindowGlide.AutomationFixture", title), title)
            handles.append(hwnd)
            w.SetWindowPos(hwnd, W.HWND(-1), 100 + index * 560, 150, 500, 420, 0x10)
        a, b, c = handles

        def activate(hwnd):
            if w.IsIconic(hwnd):
                w.ShowWindow(hwnd, 9)
            w.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 1 | 2 | 0x10)
            bounds = rect(hwnd)
            mouse(1, bounds[0] + 160, bounds[1] + 140)
            assert w.GetAncestor(w.WindowFromPoint(W.POINT(bounds[0] + 160, bounds[1] + 140)), 2) == hwnd
            mouse(2)
            mouse(4)
            w.SetForegroundWindow(hwnd)
            wait_for(lambda: w.GetForegroundWindow() == hwnd, "fixture foreground")

        def chord(letter, repeats=0, release_order=(0xA4, 0x5B, 0xA2)):
            for vk in (0xA2, 0x5B, 0xA4):
                key(vk)
            key(ord(letter))
            for _ in range(repeats):
                key(ord(letter))
            key(ord(letter), True)
            for vk in release_order:
                key(vk, True)
            assert not any(w.key_down(vk) for vk in (17, 18, 0x5B, 0x5C, ord(letter), 0xE8))
            # Let deferred dispatch and the 25 ms completion timer settle before
            # the next test directly changes the fixture's native window state.
            time.sleep(0.1)

        def competitor_messages():
            messages = []
            msg = W.MSG()
            while w.PeekMessage(C.byref(msg), None, w.WM_HOTKEY, w.WM_HOTKEY, 1):
                messages.append(msg.wParam)
            return messages

        def batch_chord(letter):
            keys = (0xA2, 0x5B, 0xA4, ord(letter))
            events = (INPUT * 8)(*[INPUT(type=1, ki=KEYBDINPUT(wVk=vk, dwFlags=flags,
                                      dwExtraInfo=w.TEST_INPUT_MARKER))
                                  for vk, flags in ([(vk, 0) for vk in keys] + [(vk, 2) for vk in reversed(keys)])])
            assert send_input(len(events), events, C.sizeof(INPUT)) == len(events)

        # A real competing registered hotkey is installed BEFORE WindowGlide.
        msg = W.MSG()
        w.PeekMessage(C.byref(msg), None, 0, 0, 0)
        w.check(w.RegisterHotKey(None, 991, 1 | 2 | 8 | 0x4000, ord("M")), "RegisterHotKey(competing test)")
        competitor = True
        activate(a)
        chord("M")
        wait_for(lambda: 991 in competitor_messages(), "competing shortcut before app")
        with log.open("w", encoding="utf-8") as output:
            app = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--test-input", "--smoke-seconds", "90"] + gesture_config_arguments("shortcuts", modifier),
                                   stdout=output, stderr=output)
            wait_for(lambda: "READY" in log.read_text(encoding="utf-8"), "app ready")
            activate(a)
            chord("M")
            wait_for(lambda: w.IsZoomed(a), "M maximizes")
            assert 991 not in competitor_messages(), "competing hotkey still received intercepted M"
            chord("M", repeats=3)
            assert w.IsZoomed(a)
            results.append("M maximizes, never toggles; hook suppresses a previously registered competing hotkey")

            chord("J", release_order=(0x5B, 0xA2, 0xA4))
            wait_for(lambda: w.IsIconic(a), "J minimizes maximized A")
            wait_for(lambda: w.GetForegroundWindow() in (b, c), "next normal fixture activated")
            chord("K")
            wait_for(lambda: not w.IsIconic(a) and w.IsZoomed(a), "K restores A maximized")
            wait_for(lambda: w.GetForegroundWindow() == a, "restored A activated")
            results.append("J activates next normal window; K restores and activates original maximized state")

            w.ShowWindow(a, 9)
            wait_for(lambda: not w.IsZoomed(a), "A restored normal")
            w.SetWindowPos(a, None, 100, 150, 500, 420, 0x4 | 0x10)
            original_a, original_b = rect(a), rect(b)

            def manual_minimize(hwnd):
                # Native system command, equivalent to the window's minimize button.
                previous = log.read_text(encoding="utf-8").count(f"Minimize tracked hwnd=0x{hwnd:X}")
                w.PostMessage(hwnd, 0x112, 0xF020, 0)
                wait_for(lambda: w.IsIconic(hwnd), "manual minimize")
                wait_for(lambda: log.read_text(encoding="utf-8").count(f"Minimize tracked hwnd=0x{hwnd:X}") > previous,
                         "manual minimize recorded")

            manual_minimize(a)
            manual_minimize(b)
            activate(c)
            chord("K")
            wait_for(lambda: not w.IsIconic(b), "LIFO restores B first")
            assert w.IsIconic(a) and rect(b) == original_b
            chord("K")
            wait_for(lambda: not w.IsIconic(a), "LIFO restores A second")
            assert rect(a) == original_a and not w.IsZoomed(a)
            results.append("manual minimize is tracked; K restores LIFO order and normal geometry")

            w.ShowWindow(a, 3)
            manual_minimize(a)
            activate(c)
            chord("K")
            wait_for(lambda: not w.IsIconic(a) and w.IsZoomed(a), "manual maximized minimize restored maximized")
            manual_minimize(a)
            w.ShowWindow(a, 9)
            wait_for(lambda: not w.IsIconic(a), "manual restore before unmaximize")
            w.ShowWindow(a, 9)
            wait_for(lambda: not w.IsZoomed(a), "manually returned to normal")
            manual_minimize(a)
            activate(c)
            chord("K")
            wait_for(lambda: not w.IsIconic(a), "latest state restored")
            assert not w.IsZoomed(a), "stale earlier maximized state was reused"
            results.append("manual maximized minimize restores maximized; later normal minimization replaces stale state")

            manual_minimize(a)
            manual_minimize(b)
            w.ShowWindow(b, 9)
            activate(c)
            chord("K")
            wait_for(lambda: not w.IsIconic(a), "skips already restored B")
            results.append("already restored windows are skipped")

            manual_minimize(a)
            manual_minimize(b)
            w.PostMessage(b, w.WM_CLOSE, 0, 0)
            wait_for(lambda: not w.IsWindow(b), "closed B")
            activate(c)
            chord("K")
            wait_for(lambda: not w.IsIconic(a), "closed record skipped")
            results.append("destroyed window records are discarded")

            activate(a)
            before_count = log.read_text(encoding="utf-8").count("Shortcut minimize hwnd=")
            chord("J", repeats=5)
            wait_for(lambda: w.IsIconic(a), "held J minimizes A")
            assert not w.IsIconic(c)
            assert log.read_text(encoding="utf-8").count("Shortcut minimize hwnd=") == before_count + 1
            chord("K")
            wait_for(lambda: not w.IsIconic(a), "release repeat scenario restored")
            results.append("held key never cascades through windows; all modifier/main-key releases remain unstuck")

            for _ in range(3):
                activate(a)
                batch_chord("J")
                wait_for(lambda: w.IsIconic(a), "batched J minimizes after release")
                wait_for(lambda: w.GetForegroundWindow() != a, "batched J focus settles")
                batch_chord("K")
                wait_for(lambda: not w.IsIconic(a) and w.GetForegroundWindow() == a, "batched K restores")
            results.append("three single-batch injected J/K cycles complete after release without stale targets")

            # Either configured drag must cleanly end when shortcut M occurs.
            activate(a)
            bounds = rect(a)
            mouse(1, bounds[0] + 180, bounds[1] + 160)
            key(w.VK_LMENU if modifier == "Alt" else 0x5B)
            mouse(2)
            mouse(1, bounds[0] + 220, bounds[1] + 195)
            wait_for(lambda: w.IsWindowVisible(w.FindWindow(GLASS_CLASS, None)), "drag overlay")
            key(0xA2)
            key(0x5B if modifier == "Alt" else w.VK_LMENU)
            key(ord("M"))
            key(ord("M"), True)
            time.sleep(0.12)
            assert not w.IsZoomed(a), "Injected M executed before modifier release"
            for vk in (0x5B, 0xA2, w.VK_LMENU):
                key(vk, True)
            wait_for(lambda: w.IsZoomed(a), "M during drag")
            wait_for(lambda: not w.IsWindowVisible(w.FindWindow(GLASS_CLASS, None)), "shortcut cleans drag overlay")
            mouse(4)
            results.append("shortcut during mouse drag ends gesture and cleans feedback before window action")

            subprocess.run([sys.executable, str(ROOT / "main.py"), "--stop"], check=True, capture_output=True, timeout=5)
            assert app.wait(timeout=5) == 0
            assert "ERROR" not in log.read_text(encoding="utf-8")
        activate(a)
        chord("M")
        wait_for(lambda: 991 in competitor_messages(), "competing shortcut restored after exit")
        results.append("exit releases keyboard interception; competing registered hotkey works again")
        for hwnd in (a, c):
            w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
        for process in fixtures:
            assert process.wait(timeout=5) == 0
        for output in outputs:
            output.close()
        for name in ("A", "B", "C"):
            events = [json.loads(line) for line in (destination / f"shortcut-fixture-{name}.jsonl").read_text(encoding="utf-8").splitlines()]
            assert not any(event.get("message") == 0x112 and event.get("wp", 0) & 0xFFF0 == 0xF100 for event in events), "unexpected Alt menu"
        results.append("no extra Alt system-menu activation observed in fixtures")
        (destination / "shortcuts.json").write_text(json.dumps({"passed": results}, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results}, indent=2))
    finally:
        mouse(4)
        mouse(16)
        for vk in (ord("J"), ord("K"), ord("M"), 0x5B, 0xA2, 0xA4):
            key(vk, True)
        if competitor:
            w.UnregisterHotKey(None, 991)
        if app and app.poll() is None:
            hwnd = w.FindWindow(w.CLASS_NAME, None)
            if hwnd:
                w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
            try:
                app.wait(timeout=4)
            except subprocess.TimeoutExpired:
                app.terminate()
                app.wait(timeout=3)
        for process, hwnd in zip(fixtures, handles):
            if process.poll() is None:
                w.PostMessage(hwnd, w.WM_CLOSE, 0, 0)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3)
        for output in outputs:
            output.close()
        set_cursor(saved_point.x, saved_point.y)
        if saved_foreground and w.IsWindow(saved_foreground):
            w.SetForegroundWindow(saved_foreground)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--modifier", choices=("Alt", "Win"), default="Alt")
    run(parser.parse_args().modifier)
