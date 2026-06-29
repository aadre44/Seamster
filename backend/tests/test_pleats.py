"""Tests for pleat geometry: allowance rule, distribution, and panel widening."""
import math

from app.patterns.geometry import Point
from app.patterns.pleats import (
    PleatSpec,
    apply_pleats,
    build_pleats,
    pleat_unit_allowance,
)
from app.patterns.skirts import PieceSpec


# ── Allowance rule ─────────────────────────────────────────────────────────────

def test_knife_allowance_is_twice_depth():
    assert pleat_unit_allowance("knife", 3.0) == 6.0
    assert pleat_unit_allowance("accordion", 3.0) == 6.0
    assert pleat_unit_allowance("pintuck", 1.0) == 2.0


def test_box_allowance_is_four_times_depth():
    assert pleat_unit_allowance("box", 3.0) == 12.0
    assert pleat_unit_allowance("inverted_box", 2.5) == 10.0


def test_zero_depth_consumes_nothing():
    assert pleat_unit_allowance("knife", 0.0) == 0.0


# ── build_pleats ───────────────────────────────────────────────────────────────

def test_build_pleats_count_and_total_knife():
    specs, total = build_pleats(0.0, 30.0, 0.0, 60.0, count=3, depth=2.0, kind="knife")
    assert len(specs) == 3                       # one fold each
    assert math.isclose(total, 3 * 2 * 2.0)      # 3 pleats x 2*depth


def test_build_pleats_box_emits_two_folds_each():
    specs, total = build_pleats(0.0, 40.0, 0.0, 50.0, count=2, depth=2.0, kind="box")
    assert len(specs) == 4                        # two folds per box pleat
    assert math.isclose(total, 2 * 4 * 2.0)


def test_build_pleats_handles_empty():
    assert build_pleats(0.0, 10.0, 0.0, 10.0, count=0, depth=2.0) == ([], 0.0)
    assert build_pleats(0.0, 10.0, 0.0, 10.0, count=3, depth=0.0) == ([], 0.0)


# ── apply_pleats ───────────────────────────────────────────────────────────────

def _rect_spec(w=20.0, h=60.0) -> PieceSpec:
    return PieceSpec(
        name="Panel",
        outline=[Point(0.0, 0.0), Point(w, 0.0), Point(w, h), Point(0.0, h)],
        darts=[],
        grain_start=Point(w / 2, 5.0),
        grain_end=Point(w / 2, h * 0.8),
    )


def test_apply_pleats_widens_panel_by_total_allowance():
    spec = _rect_spec(w=20.0)
    total = apply_pleats(spec, insert_x=0.0, count=2, depth=3.0, kind="knife")
    assert math.isclose(total, 2 * 2 * 3.0)            # 12 cm added
    assert math.isclose(max(p.x for p in spec.outline), 20.0 + 12.0)
    assert spec.pleats, "pleat markings must be attached"


def test_apply_pleats_max_y_keeps_lower_panel_width():
    """A waist pleat (max_y) widens only the top; the hem stays unchanged."""
    spec = _rect_spec(w=20.0, h=60.0)
    apply_pleats(spec, insert_x=0.0, count=1, depth=2.0, kind="knife", max_y=10.0)
    top_xs = [p.x for p in spec.outline if p.y == 0.0]
    hem_xs = [p.x for p in spec.outline if p.y == 60.0]
    assert math.isclose(max(top_xs), 20.0 + 4.0)        # widened at the waist
    assert math.isclose(max(hem_xs), 20.0)              # hem unchanged


def test_apply_pleats_noop_when_zero():
    spec = _rect_spec()
    before = [(p.x, p.y) for p in spec.outline]
    assert apply_pleats(spec, insert_x=0.0, count=0, depth=2.0) == 0.0
    assert [(p.x, p.y) for p in spec.outline] == before
    assert spec.pleats == []
