"""WindowGlide entry point."""

import argparse
import logging
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="WindowGlide: Alt + left to move, Alt + right to resize")
    parser.add_argument("--stop", action="store_true", help="Safely stop the running instance")
    parser.add_argument("--smoke-seconds", type=float, default=0, help="Exit automatically after a startup smoke test")
    parser.add_argument("--test-input", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "config.json",
                        help="Path to visual configuration JSON (restart to apply edits)")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("WindowGlide requires Windows 11")
    if args.smoke_seconds and not 0.1 <= args.smoke_seconds <= 3600:
        parser.error("--smoke-seconds must be between 0.1 and 3600")
    from windowglide.app import Application, AlreadyRunning, request_stop
    from windowglide.logging_setup import configure
    from windowglide.config import load_config

    if args.stop:
        stopped = request_stop()
        if sys.stdout:
            print("Stop requested." if stopped else "WindowGlide is not running.")
        return 0
    from windowglide import __version__

    def initialize(app):
        # Acquire the application's singleton before migrating or pruning logs.
        configure(Path(__file__).resolve().parent, console=sys.stderr is not None)
        logging.info("WindowGlide %s starting", __version__)
        app.settings = load_config(args.config)

    try:
        return Application(args.smoke_seconds, args.test_input).run(initialize)
    except AlreadyRunning:
        if sys.stderr:
            print("Already running; duplicate instance exits", file=sys.stderr)
        return 0
    except Exception as exc:
        if sys.stderr:
            print(f"WindowGlide failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
