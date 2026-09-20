import unittest
from unittest.mock import patch

from windowglide.accent import BorderColor
from windowglide.config import VisualSettings


class AccentTests(unittest.TestCase):
    @patch("windowglide.accent.read_windows_accent")
    def test_disabled_uses_config_without_reading_system(self, read):
        resolver = BorderColor(VisualSettings(border_color="#123456"))
        self.assertEqual(resolver.resolve(), "#123456")
        read.assert_not_called()

    @patch("windowglide.accent.read_windows_accent", side_effect=["#102030", "#ABCDEF"])
    def test_next_operation_reads_updated_color(self, read):
        resolver = BorderColor(VisualSettings(use_windows_accent_color=True))
        self.assertEqual(resolver.resolve(), "#102030")
        self.assertEqual(resolver.resolve(), "#ABCDEF")

    @patch("windowglide.accent.read_windows_accent", side_effect=[OSError("unavailable"), OSError("unavailable"), "#ABCDEF"])
    def test_failed_read_falls_back_without_log_spam_and_can_recover(self, read):
        resolver = BorderColor(VisualSettings(use_windows_accent_color=True, border_color="#123456"))
        with self.assertLogs("windowglide.accent", level="WARNING") as logs:
            self.assertEqual(resolver.resolve(), "#123456")
            self.assertEqual(resolver.resolve(), "#123456")
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(resolver.resolve(), "#ABCDEF")
        self.assertFalse(resolver.failed)
