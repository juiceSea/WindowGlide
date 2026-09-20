"""Small cached vector-style badges, rasterized with smooth coverage into BGRA."""

from functools import lru_cache
import math


def segments(direction):
    """Rounded strokes share one weight and arrowhead geometry in 32 DIP space."""
    if direction == "move":
        axes = ((1, 0), (0, 1))
        reach = 8.5
    else:
        diagonal = 1 / math.sqrt(2)
        axes = {"E": ((1, 0),), "W": ((1, 0),), "N": ((0, 1),), "S": ((0, 1),),
                "NW": ((diagonal, diagonal),), "SE": ((diagonal, diagonal),),
                "NE": ((diagonal, -diagonal),), "SW": ((diagonal, -diagonal),)}[direction]
        reach = 9
    lines = []
    for ux, uy in axes:
        lines.append((16 - reach * ux, 16 - reach * uy, 16 + reach * ux, 16 + reach * uy))
        for sign in (-1, 1):
            tx, ty = 16 + sign * reach * ux, 16 + sign * reach * uy
            for side in (-1, 1):
                lines.append((tx, ty, tx - sign * 3.2 * ux - side * 3.2 * uy,
                              ty - sign * 3.2 * uy + side * 3.2 * ux))
    return lines


def coverage(distance):
    return max(0.0, min(1.0, 0.5 - distance))


@lru_cache(maxsize=40)
def render_badge(direction, size):
    scale = size / 32
    strokes = []
    for x1, y1, x2, y2 in segments(direction):
        ax, ay = x1 * scale, y1 * scale
        dx, dy = (x2 - x1) * scale, (y2 - y1) * scale
        strokes.append((ax, ay, dx, dy, 1 / (dx * dx + dy * dy)))
    radius, half = 9 * scale, size / 2
    stroke_radius = 0.825 * scale
    data = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            qx, qy = abs(px - half) - (half - radius), abs(py - half) - (half - radius)
            distance = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius + 0.5
            outer = coverage(distance)
            if not outer:
                continue
            inner = coverage(distance + 0.8 * scale)
            outline = (outer - inner) / outer
            # Slightly translucent graphite with a quiet, lighter perimeter.
            color = [base + (edge - base) * outline for base, edge in zip((36, 41, 49), (95, 103, 115))]
            nearest = float("inf")
            for ax, ay, dx, dy, inverse in strokes:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) * inverse))
                nearest = min(nearest, math.hypot(px - ax - t * dx, py - ay - t * dy))
            ink = coverage(nearest - stroke_radius)
            alpha = outer * (0.96 + 0.04 * ink)
            color = [base + (ink_color - base) * ink for base, ink_color in zip(color, (245, 246, 248))]
            offset = (y * size + x) * 4
            data[offset:offset + 4] = bytes((round(color[2] * alpha), round(color[1] * alpha),
                                           round(color[0] * alpha), round(255 * alpha)))
    return bytes(data)
