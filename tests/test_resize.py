import unittest

from windowglide.resize import SizeLimits, direction_at, resized_rect


class ResizeGeometryTests(unittest.TestCase):
    def setUp(self):
        self.bounds = (-900, -300, 0, 300)
        self.limits = SizeLimits(100, 80, 1200, 900)

    def test_eight_regions_choose_expected_edges_and_corners(self):
        for point, expected in [((-800, -200), "NW"), ((-450, -200), "N"), ((-100, -200), "NE"),
                                ((-800, 0), "W"), ((-100, 0), "E"),
                                ((-800, 200), "SW"), ((-450, 200), "S"), ((-100, 200), "SE")]:
            with self.subTest(point=point):
                self.assertEqual(direction_at(self.bounds, point), expected)

    def test_center_overlap_is_inactive(self):
        self.assertIsNone(direction_at(self.bounds, (-450, 0)))
        self.assertIsNone(direction_at(self.bounds, (-539, -59)))
        self.assertIsNone(direction_at(self.bounds, (-361, 59)))

    def test_single_edge_bands_are_exactly_middle_twenty_percent(self):
        bounds = (0, 0, 1000, 1000)
        for point, expected in [((399, 200), "NW"), ((400, 200), "N"), ((599, 200), "N"),
                                ((600, 200), "NE"), ((200, 399), "NW"), ((200, 400), "W"),
                                ((200, 599), "W"), ((200, 600), "SW"), ((400, 400), None),
                                ((599, 599), None), ((600, 500), "E"), ((500, 600), "S")]:
            with self.subTest(point=point):
                self.assertEqual(direction_at(bounds, point), expected)

    def test_all_directions_preserve_opposite_edges(self):
        for direction in ("N", "S", "E", "W", "NW", "NE", "SW", "SE"):
            with self.subTest(direction=direction):
                expected = tuple(value + change for value, change in zip(self.bounds,
                    (25 if "W" in direction else 0, 30 if "N" in direction else 0,
                     25 if "E" in direction else 0, 30 if "S" in direction else 0)))
                self.assertEqual(resized_rect(self.bounds, (0, 0), (25, 30), direction, self.limits), expected)

    def test_dragging_past_opposite_edge_clamps_without_flipping(self):
        result = resized_rect(self.bounds, (0, 0), (2000, 2000), "NW", self.limits)
        self.assertEqual(result, (-100, 220, 0, 300))

    def test_maximum_size_is_obeyed(self):
        result = resized_rect(self.bounds, (0, 0), (2000, 2000), "SE", self.limits)
        self.assertEqual(result, (-900, -300, 300, 600))

    def test_invalid_application_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            SizeLimits(500, 100, 200, 300)


if __name__ == "__main__":
    unittest.main()
