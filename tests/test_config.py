import json
from pathlib import Path
import tempfile
import unittest

from windowglide.config import VisualSettings, load_config


class VisualConfigTests(unittest.TestCase):
    def test_shift_left_resize_is_opt_in_and_boolean(self):
        self.assertFalse(VisualSettings().enable_shift_left_resize)
        self.assertTrue(VisualSettings(enable_shift_left_resize=True).enable_shift_left_resize)
        for value in (1, None, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VisualSettings(enable_shift_left_resize=value)

    def test_drag_modifier_is_explicit_and_old_configs_keep_alt(self):
        self.assertEqual(VisualSettings().drag_modifier, "Alt")
        for modifier in ("Alt", "Win"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps({"drag_modifier": modifier}), encoding="utf-8")
                self.assertEqual(load_config(path).drag_modifier, modifier)
        for value in (None, True, 1, [], {}, "Ctrl", "win", "Alt+Win"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                VisualSettings(drag_modifier=value)

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
