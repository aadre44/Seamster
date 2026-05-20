"""2D geometry primitives for the pattern engine."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


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

    def __rmul__(self, scalar: float) -> Point:
        return self.__mul__(scalar)

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def midpoint(self, other: Point) -> Point:
        return Point((self.x + other.x) / 2, (self.y + other.y) / 2)

    def lerp(self, other: Point, t: float) -> Point:
        return Point(self.x + (other.x - self.x) * t, self.y + (other.y - self.y) * t)

    def normalized(self) -> Point:
        mag = math.hypot(self.x, self.y)
        if mag < 1e-12:
            return Point(0.0, 0.0)
        return Point(self.x / mag, self.y / mag)

    def perp(self) -> Point:
        """Rotate 90° counter-clockwise."""
        return Point(-self.y, self.x)

    def dot(self, other: Point) -> float:
        return self.x * other.x + self.y * other.y


@dataclass
class CurveSegment:
    """An outline vertex reached via a cubic Bezier curve from the previous vertex.

    When placed at position i in a PieceSpec.outline list, the edge from outline[i-1]
    to this vertex is drawn as a cubic Bezier rather than a straight line.
    cp1 is the control point near the previous vertex; cp2 is near this vertex.
    """
    x: float
    y: float
    cp1: Point
    cp2: Point


Polygon = list[Point]


def _signed_area(poly: Polygon) -> float:
    """Signed area via shoelace formula (positive = CCW, negative = CW in SVG)."""
    n = len(poly)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += poly[i].x * poly[j].y
        area -= poly[j].x * poly[i].y
    return area / 2.0


def offset_polygon(poly: Polygon, amount: float) -> Polygon:
    """Outset (amount > 0) or inset (amount < 0) a closed polygon by a fixed distance.

    Uses miter join at each vertex. Works for convex polygons and simple concave ones
    that don't self-intersect when offset. Amount is in the same units as the polygon coords.
    """
    n = len(poly)
    if n < 3:
        raise ValueError("Polygon must have at least 3 vertices")

    # Ensure we know the winding so we can outset in the correct direction.
    # Signed area > 0 means CCW in standard math coords (Y-up).
    # In SVG/screen coords (Y-down), > 0 means CW.
    # We offset outward regardless by checking the sign and flipping amount if needed.
    area = _signed_area(poly)
    # In screen coords, a CW polygon (area < 0) is the "normal" exterior boundary.
    # We want outset to increase the polygon size.
    # Outward normal for CW in screen coords: rotate edge dir by -90°.
    # Flip amount when area is positive (CCW in screen coords) so outset always means bigger.
    if area > 0:
        amount = -amount

    result: Polygon = []
    for i in range(n):
        prev_p = poly[(i - 1) % n]
        curr_p = poly[i]
        next_p = poly[(i + 1) % n]

        # Edge vectors
        edge_in = (curr_p - prev_p).normalized()
        edge_out = (next_p - curr_p).normalized()

        # Inward normals (perpendicular to edge, pointing left of travel direction for CW)
        normal_in = Point(-edge_in.y, edge_in.x)
        normal_out = Point(-edge_out.y, edge_out.x)

        # Average normal (miter direction)
        miter = Point(normal_in.x + normal_out.x, normal_in.y + normal_out.y)
        dot = miter.dot(miter)
        if dot < 1e-12:
            # Parallel edges — just use the normal
            result.append(Point(curr_p.x + normal_out.x * amount, curr_p.y + normal_out.y * amount))
        else:
            # Scale miter so its projection onto normal_in = amount
            proj = miter.normalized().dot(normal_in)
            if abs(proj) < 1e-6:
                proj = 1e-6
            scale = amount / proj
            miter_n = miter.normalized()
            result.append(Point(curr_p.x + miter_n.x * scale, curr_p.y + miter_n.y * scale))

    return result


def cubic_bezier_points(p0: Point, cp1: Point, cp2: Point, p1: Point, steps: int = 20) -> list[Point]:
    """Sample a cubic Bézier curve as a polyline (including endpoints)."""
    pts: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0.x + 3 * mt**2 * t * cp1.x + 3 * mt * t**2 * cp2.x + t**3 * p1.x
        y = mt**3 * p0.y + 3 * mt**2 * t * cp1.y + 3 * mt * t**2 * cp2.y + t**3 * p1.y
        pts.append(Point(x, y))
    return pts


def quadratic_bezier(p0: Point, p1: Point, p2: Point, steps: int = 20) -> list[Point]:
    """Sample a quadratic Bézier curve as a polyline (including endpoints)."""
    pts: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**2 * p0.x + 2 * mt * t * p1.x + t**2 * p2.x
        y = mt**2 * p0.y + 2 * mt * t * p1.y + t**2 * p2.y
        pts.append(Point(x, y))
    return pts


def polyline_length(pts: list[Point]) -> float:
    """Arc-length of a polyline."""
    total = 0.0
    for i in range(len(pts) - 1):
        total += pts[i].distance_to(pts[i + 1])
    return total


def cubic_bezier_length(p0: Point, cp1: Point, cp2: Point, p1: Point, steps: int = 40) -> float:
    return polyline_length(cubic_bezier_points(p0, cp1, cp2, p1, steps))
