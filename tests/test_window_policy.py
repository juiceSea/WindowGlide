from ctypes import wintypes as W
import unittest
from unittest.mock import patch, Mock

from windowglide import win32 as w
from windowglide.window_manager import is_borderless_fullscreen, WindowManager


class InactiveCenterTests(unittest.TestCase):
    def test_center_start_does_not_restore_activate_or_resize_window(self):
        manager = object.__new__(WindowManager)
        target = Mock(hwnd=123, title="Fixture")
        target.alive.return_value = True
        with patch("windowglide.window_manager.w.IsHungAppWindow", return_value=False), \
                patch("windowglide.window_manager.w.GetWindowLongPtr", return_value=w.WS_THICKFRAME), \
                patch("windowglide.window_manager.visible_rect", return_value=(0, 0, 1000, 1000)), \
                patch("windowglide.window_manager.tracking_limits") as limits, \
                patch("windowglide.window_manager.w.SetForegroundWindow") as foreground, \
                patch("windowglide.window_manager.restore_at") as restore:
            self.assertIsNone(manager.begin_resize(target, (500, 500), (900, 900)))
            limits.assert_not_called()
            foreground.assert_not_called()
            restore.assert_not_called()


class FullscreenPolicyTests(unittest.TestCase):
    def classify(self, style, bounds, maximized=False, monitor=(0, 0, 1920, 1080)):
        info = w.MONITORINFO(rcMonitor=W.RECT(*monitor))
        with patch("windowglide.window_manager.w.GetWindowLongPtr", return_value=style), \
                patch("windowglide.window_manager.w.IsZoomed", return_value=maximized), \
                patch("windowglide.window_manager.visible_rect", return_value=bounds), \
                patch("windowglide.window_manager.monitor_info", return_value=info):
            return is_borderless_fullscreen(123)

    def test_user_report_decorated_window_larger_than_screen_is_allowed(self):
        self.assertFalse(self.classify(0x14CF0000, (0, 0, 1926, 1080)))

    def test_decorated_window_exactly_filling_screen_is_allowed(self):
        self.assertFalse(self.classify(w.WS_CAPTION | w.WS_THICKFRAME, (0, 0, 1920, 1080)))

    def test_borderless_fullscreen_remains_excluded(self):
        self.assertTrue(self.classify(w.WS_THICKFRAME, (0, 0, 1920, 1080)))

    def test_borderless_window_not_filling_monitor_is_allowed(self):
        self.assertFalse(self.classify(w.WS_THICKFRAME, (100, 100, 1000, 800)))

    def test_normal_maximized_window_is_not_excluded(self):
        self.assertFalse(self.classify(w.WS_THICKFRAME, (0, 0, 1920, 1080), maximized=True))

    def test_fullscreen_detection_works_on_negative_coordinate_monitor(self):
        self.assertTrue(self.classify(w.WS_THICKFRAME, (-1920, 0, 0, 1080), monitor=(-1920, 0, 0, 1080)))


if __name__ == "__main__":
    unittest.main()
