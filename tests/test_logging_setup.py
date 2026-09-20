from datetime import date, timedelta
import logging
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from windowglide.logging_setup import RetainedFileHandler


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.day = date(2026, 9, 20)

    def handler(self, **kwargs):
        h = RetainedFileHandler(self.directory, today=lambda: self.day,
                                start_worker=False, **kwargs)
        self.addCleanup(h.close)
        return h

    def put(self, day, text='old\n', index=1):
        p = self.directory / f'windowglide.{day}.{index:06d}.log'
        p.write_text(text, encoding='utf-8')
        return p

    def emit(self, h, text):
        h.handle(logging.LogRecord('test', logging.INFO, '', 0, text, (), None))

    def test_seven_calendar_days_and_unrelated_files(self):
        expired = self.put('2026-09-13')
        oldest = self.put('2026-09-14')
        today = self.put('2026-09-20')
        other = self.directory / 'other.log'
        other.write_text('keep')
        malformed = self.directory / 'windowglide.2026-99-99.000001.log'
        malformed.write_text('keep')
        self.handler()
        self.assertFalse(expired.exists())
        self.assertTrue(all(p.exists() for p in (oldest, today, other, malformed)))

    def test_idle_maintenance_expires_open_file(self):
        h = self.handler()
        self.emit(h, 'first')
        previous = h.path
        self.day += timedelta(days=7)
        h.maintain()
        self.assertFalse(previous.exists())
        self.emit(h, 'second')
        self.assertIn(self.day.isoformat(), h.path.name)

    def test_day_rollover_preserves_recent_file(self):
        h = self.handler()
        self.emit(h, 'yesterday')
        previous = h.path
        self.day += timedelta(days=1)
        self.emit(h, 'today')
        self.assertTrue(previous.exists())
        self.assertNotEqual(previous, h.path)

    def test_size_limit_prefers_oldest_and_bounds_giant_record(self):
        old = self.put('2026-09-14', 'a' * 90)
        h = self.handler(max_bytes=300, part_bytes=100)
        for _ in range(12):
            self.emit(h, 'x' * 60)
        self.emit(h, '中' * 300)
        self.assertFalse(old.exists())
        self.assertLessEqual(sum(p.stat().st_size for p in self.directory.glob('*.log')), 300)
        for p in self.directory.glob('*.log'):
            self.assertLessEqual(p.stat().st_size, 100)
            p.read_text(encoding='utf-8')

    def test_legacy_migration_filters_records_and_keeps_traceback(self):
        legacy = self.directory / 'windowglide.log'
        legacy.write_text('2026-09-13 12:00:00,000 INFO expired\nexpired continuation\n'
                          '2026-09-14 12:00:00,000 ERROR keep\nTraceback details\n'
                          '2026-09-20 12:00:00,000 INFO current\n', encoding='utf-8')
        backup = self.directory / 'windowglide.log.1'
        backup.write_text('2026-09-15 12:00:00,000 INFO backup\n', encoding='utf-8')
        unknown = self.directory / 'windowglide.log.4'
        unknown.write_text('unmanaged')
        self.handler()
        content = ''.join(p.read_text(encoding='utf-8') for p in self.directory.glob('windowglide.*.log'))
        self.assertNotIn('expired', content)
        self.assertIn('Traceback details', content)
        self.assertIn('backup', content)
        self.assertIn('current', content)
        self.assertFalse(legacy.exists())
        self.assertFalse(backup.exists())
        self.assertTrue(unknown.exists())

    def test_delete_failure_is_retried(self):
        old = self.put('2026-09-13')
        h = self.handler()
        old = self.put('2026-09-13')
        original = Path.unlink
        def fail(p, *args, **kwargs):
            if p == old:
                raise PermissionError('locked')
            return original(p, *args, **kwargs)
        with patch.object(Path, 'unlink', fail):
            h.maintain()
            self.emit(h, 'still works')
        self.assertTrue(old.exists())
        self.assertIn('locked', h.last_cleanup_error)
        h.maintain()
        self.assertFalse(old.exists())

    def test_normal_writes_do_not_scan_directory(self):
        h = self.handler()
        self.emit(h, 'open')
        with patch.object(h, '_files', side_effect=AssertionError('unexpected scan')):
            for _ in range(100):
                self.emit(h, 'normal')

    def test_worker_waits_one_hour_and_is_interruptible(self):
        h = self.handler()
        class FakeEvent:
            def __init__(self):
                self.intervals = []
            def wait(self, interval):
                self.intervals.append(interval)
                return len(self.intervals) == 2
        event = FakeEvent()
        h.stop_event = event
        with patch.object(h, 'maintain') as maintain:
            h._worker(3600)
            maintain.assert_called_once()
        self.assertEqual(event.intervals, [3600, 3600])
        h.stop_event = threading.Event()

    def test_close_wakes_sleeping_thread(self):
        h = RetainedFileHandler(self.directory)
        h.close()
        h.worker.join(timeout=1)
        self.assertFalse(h.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
