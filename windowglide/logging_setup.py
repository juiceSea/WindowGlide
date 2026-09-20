"""Bounded daily logs; maintenance sleeps between hourly checks."""
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import re
import threading

NAME = re.compile(r"windowglide\.(\d{4}-\d{2}-\d{2})\.(\d{6})\.log\Z")
LEGACY = re.compile(r"windowglide\.log(?:\.[1-3])?\Z")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2},\d{3} ")


class RetainedFileHandler(logging.Handler):
    def __init__(self, directory, *, today=date.today, max_bytes=8_000_000,
                 part_bytes=2_000_000, interval=3600, start_worker=True):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=True)
        self.today = today
        self.max_bytes, self.part_bytes = max_bytes, part_bytes
        self.stream = self.path = self.day = None
        self.size = self.total = 0
        self.last_cleanup_error = None
        self.stop_event = threading.Event()
        self.worker = None
        self.maintain()
        self._migrate()
        self.maintain()
        if start_worker:
            self.worker = threading.Thread(target=self._worker, args=(interval,),
                                           name="LogRetention", daemon=True)
            self.worker.start()

    def _files(self):
        found = []
        for path in self.directory.iterdir():
            match = NAME.fullmatch(path.name)
            if match and path.is_file() and not path.is_symlink():
                try:
                    day = date.fromisoformat(match[1])
                    found.append((day, int(match[2]), path, path.stat().st_size))
                except (ValueError, OSError):
                    continue
        return sorted(found)

    def _close_stream(self):
        if self.stream:
            self.stream.close()
        self.stream = self.path = self.day = None
        self.size = 0

    def maintain(self, reserve=0):
        """Called at startup, hourly, date rollover, and size pressure only."""
        with self.lock:
            if self._closed:
                return
            try:
                cutoff = self.today() - timedelta(days=6)
                if self.day and self.day < cutoff:
                    self._close_stream()
                files = self._files()
                total = sum(item[3] for item in files)
                for day, _, path, size in files:
                    if day >= cutoff and total + reserve <= self.max_bytes:
                        continue
                    if path == self.path:
                        self._close_stream()
                    try:
                        path.unlink()
                        total -= size
                    except OSError as exc:
                        self.last_cleanup_error = str(exc)
                self.total = total
            except OSError as exc:
                # Never propagate a maintenance failure into window operations.
                self.last_cleanup_error = str(exc)

    def _open(self, day):
        files = [item for item in self._files() if item[0] == day]
        index = files[-1][1] if files else 0
        if files and files[-1][3] < self.part_bytes:
            path = files[-1][2]
        else:
            index += 1
            path = self.directory / f"windowglide.{day.isoformat()}.{index:06d}.log"
        self.stream = path.open("ab")
        self.path, self.day = path, day
        self.size = path.stat().st_size

    def _write(self, data, day):
        # An exceptional single giant record is bounded too.
        if len(data) > self.part_bytes:
            data = data[:self.part_bytes - 40].decode("utf-8", errors="ignore").encode("utf-8") + b"\n[oversized log record truncated]\n"
        if self.day != day or self.size + len(data) > self.part_bytes:
            self._close_stream()
            self.maintain(reserve=len(data))
            self._open(day)
            if self.size and self.size + len(data) > self.part_bytes:
                index = int(NAME.fullmatch(self.path.name)[2]) + 1
                self._close_stream()
                path = self.directory / f"windowglide.{day.isoformat()}.{index:06d}.log"
                self.stream = path.open("ab")
                self.path, self.day, self.size = path, day, path.stat().st_size
        if self.total + len(data) > self.max_bytes:
            self.maintain(reserve=len(data))
            if not self.stream:
                self._open(day)
        # Locked files may prevent deletion. Drop this record rather than grow unbounded.
        if self.total + len(data) > self.max_bytes:
            return
        self.stream.write(data)
        self.stream.flush()
        self.size += len(data)
        self.total += len(data)

    def emit(self, record):
        if self._closed:
            return
        try:
            self._write((self.format(record) + "\n").encode("utf-8"), self.today())
        except Exception:
            self.handleError(record)

    def _migrate(self):
        cutoff = self.today() - timedelta(days=6)
        sources = sorted((p for p in self.directory.iterdir() if LEGACY.fullmatch(p.name)
                          and p.is_file() and not p.is_symlink()),
                         key=lambda p: int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0,
                         reverse=True)
        for path in sources:
            try:
                fallback = datetime.fromtimestamp(path.stat().st_mtime).date()
                day = fallback
                # Stream line-by-line; traceback continuations inherit their record date.
                with path.open("r", encoding="utf-8", errors="replace") as source:
                    for line in source:
                        match = STAMP.match(line)
                        if match:
                            try:
                                day = date.fromisoformat(match[1])
                            except ValueError:
                                day = fallback
                        if day >= cutoff:
                            self._write(line.encode("utf-8"), day)
                path.unlink()
            except OSError as exc:
                # Leave source intact on failure, retry at next startup.
                self.last_cleanup_error = str(exc)
        self._close_stream()

    def _worker(self, interval):
        while not self.stop_event.wait(interval):
            self.maintain()

    def close(self):
        self.stop_event.set()
        # Do not join here: logging.shutdown can hold this handler's lock.
        with self.lock:
            self._closed = True
            self._close_stream()
        super().close()


def configure(root, console=True):
    handler = RetainedFileHandler(root / "logs")
    handlers = [handler]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                        handlers=handlers, force=True)
    if handler.last_cleanup_error:
        logging.warning("Log retention could not complete; will retry: %s", handler.last_cleanup_error)
