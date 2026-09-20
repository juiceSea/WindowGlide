"""Coordinate helpers, independent of Win32 for deterministic tests."""


def moved_origin(initial_rect, initial_point, current_point):
    return (initial_rect[0] + current_point[0] - initial_point[0],
            initial_rect[1] + current_point[1] - initial_point[1])


def restored_origin(point, maximized_rect, restored_size, work_area, title_height=32):
    """Preserve proportional client-area grip and keep the title strip reachable."""
    x, y = point
    left, top, right, bottom = maximized_rect
    width, height = restored_size
    fraction = min(1.0, max(0.0, (x - left) / max(1, right - left)))
    fraction_y = min(1.0, max(0.0, (y - top) / max(1, bottom - top)))
    new_x, new_y = round(x - fraction * width), round(y - fraction_y * height)
    wl, wt, wr, wb = work_area
    new_x = max(wl - width + title_height, min(new_x, wr - title_height))
    new_y = max(wt, min(new_y, wb - title_height))
    return new_x, new_y
