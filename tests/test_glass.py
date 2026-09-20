import unittest
from unittest.mock import Mock, patch

from windowglide.glass import classify, sample_glass, WHITE, GRAY
from windowglide.overlay import Overlay, GLASS_CLASS
from windowglide.config import VisualSettings


class GlassTests(unittest.TestCase):
    def test_light_and_dark_content(self):
        self.assertEqual(classify(bytes((250, 250, 250, 0)) * 16).color, GRAY)
        self.assertEqual(classify(bytes((25, 25, 25, 0)) * 16).color, WHITE)

    def test_area_mix_instead_of_single_bright_point(self):
        dark, light = bytes((0, 0, 0, 0)), bytes((255, 255, 255, 0))
        self.assertEqual(classify(dark * 15 + light).color, WHITE)
        self.assertEqual(classify(light * 15 + dark).color, GRAY)
        self.assertEqual(classify(b"").color, WHITE)

    @patch("windowglide.glass.w.IsWindowVisible", return_value=False)
    @patch("windowglide.glass.GetDC")
    def test_hidden_window_falls_back_without_capture(self, get_dc, visible):
        self.assertEqual(sample_glass(123).color, WHITE)
        get_dc.assert_not_called()

    @patch("windowglide.overlay.sample_glass")
    def test_disabled_adaptation_never_samples(self, sample):
        overlay = object.__new__(Overlay)
        overlay.settings = VisualSettings(adaptive_glass_color=False)
        overlay.windows = {GLASS_CLASS: 123}
        self.assertEqual(overlay.choose_glass_color(Mock(), (0, 0), False), WHITE)
        sample.assert_not_called()

    @patch("windowglide.overlay.visible_rect", return_value=(0, 0, 100, 100))
    @patch("windowglide.overlay.sample_glass")
    def test_inactive_resize_center_never_samples(self, sample, bounds):
        overlay = object.__new__(Overlay)
        overlay.settings = VisualSettings()
        overlay.windows = {GLASS_CLASS: 123}
        self.assertEqual(overlay.choose_glass_color(Mock(), (50, 50), True), WHITE)
        sample.assert_not_called()
