"""Tests for the reusable edge-finish generators (bindings + shaped facings)."""
import math

from app.patterns.finishings import (
    make_armhole_facing,
    make_edge_binding,
    make_edge_facing,
    make_hem_facing,
    path_length,
)
from app.patterns.geometry import CurveSegment, Point

SA = 1.5


def test_path_length_straight_polyline():
    pts = [Point(0.0, 0.0), Point(3.0, 0.0), Point(3.0, 4.0)]
    assert math.isclose(path_length(pts), 7.0, rel_tol=1e-6)


def test_path_length_expands_curve():
    # A curve from (0,0) to (10,0) bows out, so its arc length exceeds the 10 cm chord.
    curve = CurveSegment(10.0, 0.0, cp1=Point(2.0, 6.0), cp2=Point(8.0, 6.0))
    length = path_length([Point(0.0, 0.0), curve])
    assert length > 10.0


def test_binding_length_matches_edge_run():
    run = 48.0
    strip = make_edge_binding("Neckline Binding", run, 1.0, SA, contrast=True)
    xs = [p.x for p in strip.outline]
    longer_dim = max(xs) - min(xs)
    # The strip's length equals the edge run-length (plus a little to turn the ends).
    assert math.isclose(longer_dim, run + 2.0, rel_tol=1e-6)


def test_binding_contrast_is_flagged_in_notes():
    strip = make_edge_binding("Neckline Binding", 30.0, 1.0, SA, contrast=True)
    assert "CONTRAST" in strip.notes.upper()
    plain = make_edge_binding("Hem Binding", 30.0, 1.0, SA, contrast=False)
    assert "CONTRAST FABRIC" not in plain.notes.upper()


def test_edge_facing_inner_band_sits_toward_interior():
    # A vertical edge at x=10; interior is to the left at x=0.
    edge = [Point(10.0, 0.0), Point(10.0, 10.0)]
    interior = Point(0.0, 5.0)
    facing = make_edge_facing("F", edge, 3.0, interior, SA)
    # Every outline point lies between the edge (x=10) and the interior side,
    # and at least one inner point is offset ~3 cm inward (toward x=7).
    xs = [p.x for p in facing.outline]
    assert min(xs) <= 7.5, "inner band should be offset inward by ~depth"
    assert max(xs) <= 10.0 + 1e-6


def test_armhole_facing_follows_curve_and_cuts_four():
    armhole = [Point(16.0, 2.0), CurveSegment(25.0, 28.0, cp1=Point(16.0, 14.0), cp2=Point(26.0, 24.0))]
    facing = make_armhole_facing(armhole, Point(0.0, 28.0), SA, depth_cm=5.0, cut_qty=4)
    assert facing.name == "Armhole Facing"
    assert facing.cut_qty == 4
    # The curve was expanded, so the facing has many following points (not a 4-pt rectangle).
    assert len(facing.outline) > 8


def test_hem_facing_offsets_upward():
    L = 60.0
    hem = [Point(0.0, L), Point(25.0, L)]
    facing = make_hem_facing(hem, Point(12.5, L - 14.0), SA, depth_cm=5.0)
    ys = [p.y for p in facing.outline]
    # The inner edge is pushed up (smaller y) from the hemline.
    assert min(ys) < L
