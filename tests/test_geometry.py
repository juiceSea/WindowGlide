import unittest

from windowglide.geometry import moved_origin, restored_origin


class GeometryTests(unittest.TestCase):
    def test_move_with_negative_monitor_coordinates(self):
        self.assertEqual(moved_origin((-1800, -200, -800, 500), (-1500, -100), (-1600, -150)), (-1900, -250))

    def test_large_virtual_desktop_does_not_truncate_coordinates(self):
        self.assertEqual(moved_origin((35000, 0, 36000, 500), (35400, 100), (35500, 150)), (35100, 50))

    def test_maximized_grip_on_left_monitor(self):
        result = restored_origin((-960, 500), (-1920, 0, 0, 1080), (1000, 700), (-1920, 0, 0, 1040))
        self.assertEqual(result, (-1460, 176))

    def test_title_strip_remains_reachable_when_restoring_near_bottom(self):
        x, y = restored_origin((1900, 1030), (0, 0, 1920, 1080), (1000, 700), (0, 0, 1920, 1040))
        self.assertLessEqual(y, 1008)
        self.assertGreaterEqual(y, 0)
        self.assertLess(x, 1920)


if __name__ == "__main__":
    unittest.main()
