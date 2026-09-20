"""Live lifecycle checks without sending keyboard/mouse input."""

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


def run():
    if w.FindWindow(w.CLASS_NAME, None):
        raise RuntimeError("Stop WindowGlide before running startup checks")
    report = {}
    w.check(w.RegisterHotKey(None, 0x5747, 0x400B, ord("Q")), "Reserve hotkey for conflict test")
    try:
        child = subprocess.run([sys.executable, str(ROOT / "main.py"), "--smoke-seconds", "0.2"],
                               capture_output=True, text=True, timeout=5)
        assert child.returncode == 1, child.stderr
        assert "RegisterHotKey" in child.stderr and "READY" not in child.stderr, child.stderr
        assert not w.FindWindow(w.CLASS_NAME, None)
        report["hotkey_conflict"] = "startup refused before installing hooks; resources released"
    finally:
        w.UnregisterHotKey(None, 0x5747)

    get_times = w.bind(w.kernel32, "GetProcessTimes", W.BOOL, W.HANDLE,
                       *[C.POINTER(W.FILETIME)] * 4)

    def cpu_seconds(process):
        times = [W.FILETIME() for _ in range(4)]
        w.check(get_times(process, *[C.byref(value) for value in times]), "GetProcessTimes")
        return sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in times[2:]) / 10_000_000

    child = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--smoke-seconds", "4"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    handle = None
    try:
        handle = w.check(w.OpenProcess(0x1000, False, child.pid), "OpenProcess(sample CPU)")
        time.sleep(0.6)
        assert child.poll() is None, "Application failed to start after hotkey conflict test"
        start_cpu, start = cpu_seconds(handle), time.perf_counter()
        time.sleep(2)
        report["idle_sample"] = {"duration_seconds": round(time.perf_counter() - start, 3),
                                 "cpu_seconds": round(cpu_seconds(handle) - start_cpu, 6)}
        out, err = child.communicate(timeout=5)
        assert child.returncode == 0 and "READY" in err and "STOPPED" in err, out + err
        report["restart_after_failed_startup"] = "passed"
        assert not w.FindWindow(w.CLASS_NAME, None)
    finally:
        if handle:
            w.CloseHandle(handle)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
    destination = ROOT / "test-results" / "startup.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
