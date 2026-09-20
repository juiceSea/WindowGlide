import json
from pathlib import Path
import tempfile
import unittest

from windowglide.config import VisualSettings, load_config


class VisualConfigTests(unittest.TestCase):
    def test_missing_config_is_created_with_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertEqual(load_config(path), VisualSettings())
            self.assertEqual(json.loads(path.read_text())["glass_opacity"], 0.20)

    def test_partial_config_keeps_unmodified_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"enable_glass": false, "border_width": 4}', encoding="utf-8")
            settings = load_config(path)
            self.assertFalse(settings.enable_glass)
            self.assertEqual(settings.border_width, 4)
            self.assertEqual(settings.border_color, "#7C9BC5")
            self.assertFalse(settings.use_windows_accent_color)

    def test_invalid_visual_values_are_rejected(self):
        for values in ({"glass_opacity": -0.1}, {"glass_opacity": float("nan")}, {"border_width": True},
                       {"enable_border": "false"}, {"border_color": "yellow"}, {"corner_radius": -1},
                       {"use_windows_accent_color": "true"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                VisualSettings(**values)

    def test_unknown_fields_are_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"glass_opactiy": 0.2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
