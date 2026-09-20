"""Validated gesture, visual and shortcut settings, loaded once at startup."""

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path
import re


@dataclass(frozen=True)
class VisualSettings:
    drag_modifier: str = "Alt"
    border_width: float = 3
    border_color: str = "#7C9BC5"
    use_windows_accent_color: bool = False
    glass_opacity: float = 0.20
    adaptive_glass_color: bool = True
    corner_radius: float = 8
    enable_border: bool = True
    enable_glass: bool = True
    enable_cursor_change: bool = True
    enable_window_shortcuts: bool = True
    shortcut_minimize: str = "Ctrl+Win+Alt+J"
    shortcut_restore: str = "Ctrl+Win+Alt+K"
    shortcut_maximize: str = "Ctrl+Win+Alt+M"

    def __post_init__(self):
        if self.drag_modifier not in ("Alt", "Win"):
            raise ValueError('drag_modifier must be "Alt" or "Win"')
        for name, low, high in (("border_width", 1, 20), ("glass_opacity", 0, 1), ("corner_radius", 0, 32)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be a finite number between {low} and {high}")
        if not isinstance(self.border_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.border_color):
            raise ValueError("border_color must be a six-digit #RRGGBB color")
        for name in ("enable_border", "enable_glass", "enable_cursor_change", "use_windows_accent_color", "adaptive_glass_color", "enable_window_shortcuts"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true or false")
        from .shortcuts import bindings_for
        bindings_for(self)


def load_config(path: Path):
    if not path.exists():
        settings = VisualSettings()
        try:
            with path.open("x", encoding="utf-8") as file:
                json.dump(asdict(settings), file, indent=2)
                file.write("\n")
        except FileExistsError:
            return load_config(path)
        return settings
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict):
        raise ValueError("config.json must contain a JSON object")
    unknown = values.keys() - {field.name for field in fields(VisualSettings)}
    if unknown:
        raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}")
    return VisualSettings(**values)
