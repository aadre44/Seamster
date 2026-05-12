"""Tests for app.patterns.geometry — Point math, bezier sampling, polygon offset."""
import math
import pytest
from app.patterns.geometry import (
    Point,
    cubic_bezier_length,
    cubic_bezier_points,
    offset_polygon,
    polyline_length,
    quadratic_bezier,
)

TOLERANCE = 2e-3  # 2 mm


# ── Point arithmetic ──────────────────────────────────────────────────────────

def test_point_add():
    assert Point(1, 2) + Point(3, 4) == Point(4, 6)


def test_point_sub():
    assert Point(5, 3) - Point(2, 1) == Point(3, 2)


def test_point_mul():
    assert Point(2, 3) * 2 == Point(4, 6)


def test_point_rmul():
    assert 3 * Point(1, 2) == Point(3, 6)


def test_point_distance():
    assert math.isclose(Point(0, 0).distance_to(Point(3, 4)), 5.0)


def test_point_midpoint():
    assert Point(0, 0).midpoint(Point(4, 6)) == Point(2, 3)


def test_point_lerp_endpoints():
    a, b = Point(0, 0), Point(10, 0)
    assert a.lerp(b, 0.0) == a
    assert a.lerp(b, 1.0) == b


def test_point_lerp_midpoint():
    a, b = Point(0, 0), Point(10, 0)
    mid = a.lerp(b, 0.5)
    assert math.isclose(mid.x, 5.0) and math.isclose(mid.y, 0.0)


def test_point_normalized_unit():
    n = Point(3, 4).normalized()
    mag = math.hypot(n.x, n.y)
    assert math.isclose(mag, 1.0)


def test_point_normalized_zero():
    assert Point(0, 0).normalized() == Point(0, 0)


def test_point_perp():
    # Rotating (1, 0) by 90° CCW should give (0, 1)
    p = Point(1, 0).perp()
    assert math.isclose(p.x, 0.0) and math.isclose(p.y, 1.0)


# ── Bezier sampling ───────────────────────────────────────────────────────────

def test_quadratic_bezier_endpoints():
    p0, p1, p2 = Point(0, 0), Point(5, 10), Point(10, 0)
    pts = quadratic_bezier(p0, p1, p2, steps=10)
    assert pts[0] == p0
    assert pts[-1] == p2


def test_quadratic_bezier_count():
    pts = quadratic_bezier(Point(0, 0), Point(5, 5), Point(10, 0), steps=20)
    assert len(pts) == 21  # steps + 1


def test_cubic_bezier_endpoints():
    p0, cp1, cp2, p1 = Point(0, 0), Point(0, 10), Point(20, 10), Point(20, 0)
    pts = cubic_bezier_points(p0, cp1, cp2, p1, steps=20)
    assert math.isclose(pts[0].x, p0.x) and math.isclose(pts[0].y, p0.y)
    assert math.isclose(pts[-1].x, p1.x) and math.isclose(pts[-1].y, p1.y)


def test_cubic_bezier_straight_line():
    # Control points collinear → bezier is a straight line
    p0, p1 = Point(0, 0), Point(10, 0)
    cp1, cp2 = Point(3.33, 0), Point(6.67, 0)
    pts = cubic_bezier_points(p0, cp1, cp2, p1, steps=10)
    for pt in pts:
        assert abs(pt.y) < 1e-6


def test_cubic_bezier_length_straight():
    # Straight line of length 10 — arc length should be ≈ 10
    p0, p1 = Point(0, 0), Point(10, 0)
    cp1, cp2 = Point(3.33, 0), Point(6.67, 0)
    length = cubic_bezier_length(p0, cp1, cp2, p1, steps=50)
    assert math.isclose(length, 10.0, abs_tol=TOLERANCE)


def test_polyline_length_triangle():
    pts = [Point(0, 0), Point(3, 0), Point(3, 4)]
    assert math.isclose(polyline_length(pts), 7.0)


# ── Polygon offset ────────────────────────────────────────────────────────────

def _square(size: float) -> list[Point]:
    """A clockwise square in SVG screen coords (Y-down)."""
    return [
        Point(0, 0),
        Point(size, 0),
        Point(size, size),
        Point(0, size),
    ]


def test_offset_polygon_outset_increases_area():
    sq = _square(10.0)
    expanded = offset_polygon(sq, 1.0)  # outset by 1 cm
    # Each side should move outward → larger bounding box
    xs = [p.x for p in expanded]
    ys = [p.y for p in expanded]
    assert min(xs) < 0  # left edge moved left
    assert max(xs) > 10  # right edge moved right
    assert min(ys) < 0  # top edge moved up
    assert max(ys) > 10  # bottom edge moved down


def test_offset_polygon_outset_amount():
    sq = _square(10.0)
    amount = 1.5
    expanded = offset_polygon(sq, amount)
    # For a convex square, each corner moves diagonally by amount√2, but each edge
    # moves outward by exactly `amount`.
    # Check that the mid-point of each edge is offset by the correct amount.
    # Top edge midpoint should be at y = -amount (moved up from y=0)
    xs = sorted([p.x for p in expanded])
    ys = sorted([p.y for p in expanded])
    assert math.isclose(min(ys), -amount, abs_tol=TOLERANCE)
    assert math.isclose(max(ys), 10 + amount, abs_tol=TOLERANCE)
    assert math.isclose(min(xs), -amount, abs_tol=TOLERANCE)
    assert math.isclose(max(xs), 10 + amount, abs_tol=TOLERANCE)


def test_offset_polygon_inset():
    sq = _square(10.0)
    shrunk = offset_polygon(sq, -1.0)  # inset
    xs = [p.x for p in shrunk]
    assert min(xs) > 0 and max(xs) < 10


def test_offset_polygon_preserves_vertex_count():
    sq = _square(10.0)
    assert len(offset_polygon(sq, 1.0)) == 4
