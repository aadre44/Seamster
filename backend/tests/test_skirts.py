"""Tests for the Aldrich straight skirt base block."""
import math
import pytest
from app.models.measurements import Measurements
from app.patterns.geometry import polyline_length
from app.patterns.skirts import build_straight_skirt_block

TOLERANCE = 2e-3  # ±2 mm (as specified in acceptance criteria)


def _measurements(**overrides) -> Measurements:
    defaults = dict(waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0)
    defaults.update(overrides)
    return Measurements(**defaults)


def _perimeter(outline) -> float:
    """Sum of all side lengths of a closed polygon."""
    n = len(outline)
    total = 0.0
    for i in range(n):
        total += outline[i].distance_to(outline[(i + 1) % n])
    return total


# ── Basic structure ───────────────────────────────────────────────────────────

def test_returns_front_and_back():
    pieces = build_straight_skirt_block(_measurements())
    assert "front" in pieces
    assert "back" in pieces


def test_outline_is_closed_polygon():
    pieces = build_straight_skirt_block(_measurements())
    for spec in pieces.values():
        assert len(spec.outline) >= 4


def test_grain_line_is_vertical():
    """Grain line should run parallel to center-front/back (i.e. same x, different y)."""
    pieces = build_straight_skirt_block(_measurements())
    for spec in pieces.values():
        assert math.isclose(spec.grain_start.x, spec.grain_end.x, abs_tol=TOLERANCE)


def test_grain_line_runs_length_of_piece():
    """Grain line should span at least 40 % of the skirt length."""
    m = _measurements(length_cm=65.0)
    pieces = build_straight_skirt_block(m)
    for spec in pieces.values():
        gl_len = abs(spec.grain_end.y - spec.grain_start.y)
        assert gl_len > 0.4 * m.length_cm


# ── Hip width ─────────────────────────────────────────────────────────────────

def test_front_hip_width():
    m = _measurements(hip_cm=94.0)
    expected = (94.0 + 2.0) / 4
    pieces = build_straight_skirt_block(m)
    front = pieces["front"]
    # The widest x in the outline should equal hip_qt
    max_x = max(p.x for p in front.outline)
    assert math.isclose(max_x, expected, abs_tol=TOLERANCE)


def test_back_hip_width():
    m = _measurements(hip_cm=94.0)
    expected = (94.0 + 2.0) / 4
    pieces = build_straight_skirt_block(m)
    back = pieces["back"]
    max_x = max(p.x for p in back.outline)
    assert math.isclose(max_x, expected, abs_tol=TOLERANCE)


# ── Dart intake ───────────────────────────────────────────────────────────────

def test_front_dart_intake_equals_hip_minus_waist_quarter():
    m = _measurements(waist_cm=76.0, hip_cm=94.0)
    hip_qt = (94.0 + 2.0) / 4  # 24.0
    w_qt_f = 76.0 / 4 + 0.5    # 19.5  (Aldrich front balance correction)
    expected_intake = hip_qt - w_qt_f
    pieces = build_straight_skirt_block(m)
    front = pieces["front"]
    total_dart = sum(d.width for d in front.darts)
    assert math.isclose(total_dart, expected_intake, abs_tol=TOLERANCE)


def test_back_dart_total_intake():
    m = _measurements(waist_cm=76.0, hip_cm=94.0)
    hip_qt = (94.0 + 2.0) / 4
    w_qt_b = 76.0 / 4 - 0.5    # Aldrich back balance correction
    expected_intake = hip_qt - w_qt_b
    pieces = build_straight_skirt_block(m)
    back = pieces["back"]
    total_dart = sum(d.width for d in back.darts)
    assert math.isclose(total_dart, expected_intake, abs_tol=TOLERANCE)


def test_front_has_one_dart():
    pieces = build_straight_skirt_block(_measurements())
    assert len(pieces["front"].darts) == 1


def test_back_has_two_darts():
    pieces = build_straight_skirt_block(_measurements())
    assert len(pieces["back"].darts) == 2


def test_dart_legs_are_within_waist_line():
    """Dart legs must not extend beyond the waist seam or past center."""
    pieces = build_straight_skirt_block(_measurements())
    for name, spec in pieces.items():
        waist_width = max(p.x for p in spec.outline if math.isclose(p.y, 0.0, abs_tol=TOLERANCE))
        for dart in spec.darts:
            assert dart.center_x - dart.width / 2 >= 0
            assert dart.center_x + dart.width / 2 <= waist_width + TOLERANCE


# ── Length ────────────────────────────────────────────────────────────────────

def test_piece_length_matches_measurement():
    m = _measurements(length_cm=65.0)
    pieces = build_straight_skirt_block(m)
    for spec in pieces.values():
        max_y = max(p.y for p in spec.outline)
        assert math.isclose(max_y, m.length_cm, abs_tol=TOLERANCE)


# ── On-fold / cut quantity ────────────────────────────────────────────────────

def test_front_is_on_fold():
    pieces = build_straight_skirt_block(_measurements())
    assert pieces["front"].on_fold is True


def test_back_is_not_on_fold():
    pieces = build_straight_skirt_block(_measurements())
    assert pieces["back"].on_fold is False


# ── Golden-file skirts (5 standard sizes, ±2 mm tolerance) ───────────────────

GOLDEN_CASES = [
    # (label, waist, hip, wh, length)  — UK standard sizing (Aldrich base)
    ("UK12", 76.0, 94.0, 21.0, 65.0),
    ("UK14", 80.0, 98.0, 21.5, 65.0),
    ("UK16", 84.0, 102.0, 22.0, 67.0),
    ("UK18", 88.0, 106.0, 22.5, 67.0),
    ("UK20", 92.0, 110.0, 23.0, 69.0),
]


@pytest.mark.parametrize("label,waist,hip,wh,length", GOLDEN_CASES)
def test_golden_hip_width(label, waist, hip, wh, length):
    m = _measurements(waist_cm=waist, hip_cm=hip, waist_to_hip_cm=wh, length_cm=length)
    pieces = build_straight_skirt_block(m)
    expected_hip_qt = (hip + 2.0) / 4
    for spec in pieces.values():
        max_x = max(p.x for p in spec.outline)
        assert math.isclose(max_x, expected_hip_qt, abs_tol=TOLERANCE), \
            f"{label} {spec.name}: expected hip_qt={expected_hip_qt:.2f} got {max_x:.2f}"


@pytest.mark.parametrize("label,waist,hip,wh,length", GOLDEN_CASES)
def test_golden_waist_circumference(label, waist, hip, wh, length):
    """After removing all dart intake, the total waist seam = W."""
    m = _measurements(waist_cm=waist, hip_cm=hip, waist_to_hip_cm=wh, length_cm=length)
    pieces = build_straight_skirt_block(m)
    # Each half-panel (front/back) waist = hip_qt - total_dart_intake
    # Combined 4 quarter-panels = W (full circle)
    total_waist = 0.0
    for spec in pieces.values():
        hip_qt = max(p.x for p in spec.outline)
        total_dart = sum(d.width for d in spec.darts)
        total_waist += (hip_qt - total_dart) * 2  # × 2 for both halves
    assert math.isclose(total_waist, waist, abs_tol=TOLERANCE * 4), \
        f"{label}: total waist {total_waist:.2f} ≠ {waist:.2f}"


@pytest.mark.parametrize("label,waist,hip,wh,length", GOLDEN_CASES)
def test_golden_length(label, waist, hip, wh, length):
    m = _measurements(waist_cm=waist, hip_cm=hip, waist_to_hip_cm=wh, length_cm=length)
    pieces = build_straight_skirt_block(m)
    for spec in pieces.values():
        max_y = max(p.y for p in spec.outline)
        assert math.isclose(max_y, length, abs_tol=TOLERANCE), \
            f"{label} {spec.name}: length {max_y:.2f} ≠ {length:.2f}"
