"""2D geometry primitives for the pattern engine. Implemented in Task 3."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Point:
    x: float
    y: float

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def midpoint(self, other: Point) -> Point:
        return Point((self.x + other.x) / 2, (self.y + other.y) / 2)


Polygon = list[Point]


def offset_polygon(poly: Polygon, amount: float) -> Polygon:
    """Inset (amount > 0) or outset (amount < 0) a closed polygon by a fixed distance.
    Stub — full implementation in Task 3.
    """
    raise NotImplementedError("offset_polygon not yet implemented (Task 3)")


def quadratic_bezier(p0: Point, p1: Point, p2: Point, steps: int = 20) -> list[Point]:
    """Sample a quadratic Bézier curve as a polyline.
    Stub — full implementation in Task 3.
    """
    raise NotImplementedError("quadratic_bezier not yet implemented (Task 3)")
