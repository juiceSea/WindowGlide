"""40/20/40 sizing regions with an inactive center and fixed opposite edges."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SizeLimits:
    min_width: int
    min_height: int
    max_width: int
    max_height: int

    def __post_init__(self):
        if not (0 < self.min_width <= self.max_width and 0 < self.min_height <= self.max_height):
            raise ValueError("Invalid window tracking-size limits")


def direction_at(bounds, point):
    left, top, right, bottom = bounds
    x, y = point
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError("Invalid window bounds")
    def region(offset, length):
        # Integer comparisons make the 40% and 60% boundaries deterministic.
        return 0 if offset * 5 < length * 2 else 1 if offset * 5 < length * 3 else 2

    column, row = region(x - left, width), region(y - top, height)
    return (("NW", "N", "NE"), ("W", None, "E"), ("SW", "S", "SE"))[row][column]


def resized_rect(initial_rect, initial_point, current_point, direction, limits):
    if direction not in {"N", "S", "E", "W", "NW", "NE", "SW", "SE"}:
        raise ValueError("Unknown resize direction")
    left, top, right, bottom = initial_rect
    dx, dy = current_point[0] - initial_point[0], current_point[1] - initial_point[1]
    if "W" in direction:
        left = max(right - limits.max_width, min(left + dx, right - limits.min_width))
    elif "E" in direction:
        right = max(left + limits.min_width, min(right + dx, left + limits.max_width))
    if "N" in direction:
        top = max(bottom - limits.max_height, min(top + dy, bottom - limits.min_height))
    elif "S" in direction:
        bottom = max(top + limits.min_height, min(bottom + dy, top + limits.max_height))
    return left, top, right, bottom
