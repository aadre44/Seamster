"""Tests for silhouette modifiers (pencil, a-line, gathered, circle, wrap)."""
import math
import pytest
from app.models.features import ClosureFeature, DartFeature, SkirtFeatures, WaistbandFeature
from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.modifiers import apply_silhouette
from app.patterns.skirts import build_straight_skirt_block

TOLERANCE = 2e-3  # ±2 mm


def _meas(**kw) -> Measurements:
    base = dict(waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0)
    base.update(kw)
    return Measurements(**base)


def _features(silhouette: str, **kw) -> SkirtFeatures:
    return SkirtFeatures(
        silhouette=silhouette,
        length_category="knee",
        waistband=WaistbandFeature(type="straight", width_cm_estimate=3.0),
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        darts=DartFeature(front=1, back=2),
        details=[],
        confidence=0.9,
        notes="",
        **kw,
    )


def _base_pieces(m: Measurements):
    return build_straight_skirt_block(m)


def _hem_x(spec) -> float:
    """Return the x-coordinate of the side-seam hem point (index 3)."""
    return spec.outline[3].x


def _hip_x(spec) -> float:
    """Return the x-coordinate of the side-seam hip point (index 2)."""
    return spec.outline[2].x


# ── Straight (no-op) ──────────────────────────────────────────────────────────

def test_straight_silhouette_no_change():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("straight"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), _hem_x(base[name]), abs_tol=TOLERANCE)


def test_gathered_silhouette_no_shape_change():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("gathered"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), _hem_x(base[name]), abs_tol=TOLERANCE)


def test_pleated_silhouette_no_shape_change():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("pleated"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), _hem_x(base[name]), abs_tol=TOLERANCE)


# ── Pencil ────────────────────────────────────────────────────────────────────

def test_pencil_hem_narrower_than_hip():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("pencil"), m)
    for name in ("front", "back"):
        assert _hem_x(result[name]) < _hip_x(result[name]) + TOLERANCE


def test_pencil_hem_is_90pct_of_hip():
    m = _meas(hip_cm=94.0)
    hip_qt = (94.0 + 2.0) / 4
    expected_hem = hip_qt * 0.90
    result = apply_silhouette(_base_pieces(m), _features("pencil"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), expected_hem, abs_tol=TOLERANCE)


def test_pencil_preserves_outline_length():
    m = _meas()
    result = apply_silhouette(_base_pieces(m), _features("pencil"), m)
    for spec in result.values():
        assert len(spec.outline) == 5


# ── A-line ────────────────────────────────────────────────────────────────────

def test_a_line_hem_wider_than_hip():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("a_line"), m)
    for name in ("front", "back"):
        assert _hem_x(result[name]) > _hip_x(base[name]) - TOLERANCE


def test_a_line_flare_amount():
    m = _meas(hip_cm=94.0)
    hip_qt = (94.0 + 2.0) / 4
    expected_hem = hip_qt + 5.0
    result = apply_silhouette(_base_pieces(m), _features("a_line"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), expected_hem, abs_tol=TOLERANCE)


def test_a_line_preserves_outline_length():
    m = _meas()
    result = apply_silhouette(_base_pieces(m), _features("a_line"), m)
    for spec in result.values():
        assert len(spec.outline) == 5


# ── Circle ────────────────────────────────────────────────────────────────────

def test_circle_hem_twice_hip():
    m = _meas(hip_cm=94.0)
    hip_qt = (94.0 + 2.0) / 4
    expected_hem = hip_qt * 2.0
    result = apply_silhouette(_base_pieces(m), _features("circle"), m)
    for name in ("front", "back"):
        assert math.isclose(_hem_x(result[name]), expected_hem, abs_tol=TOLERANCE)


# ── Wrap ──────────────────────────────────────────────────────────────────────

def test_wrap_front_is_wider_than_back():
    m = _meas()
    result = apply_silhouette(_base_pieces(m), _features("wrap"), m)
    assert _hem_x(result["front"]) > _hem_x(result["back"]) + TOLERANCE


def test_wrap_front_not_on_fold():
    m = _meas()
    result = apply_silhouette(_base_pieces(m), _features("wrap"), m)
    assert result["front"].on_fold is False


def test_wrap_back_unchanged():
    m = _meas()
    base = _base_pieces(m)
    result = apply_silhouette(base, _features("wrap"), m)
    assert math.isclose(_hem_x(result["back"]), _hem_x(base["back"]) + 4.0, abs_tol=TOLERANCE)


# ── Engine round-trip: generates valid .psnap ─────────────────────────────────

def test_engine_generates_valid_psnap():
    from app.patterns.engine import generate_pattern
    m = _meas()
    f = _features("straight")
    psnap = generate_pattern(f, m)
    assert psnap["version"] == 1
    assert isinstance(psnap["elements"], list)
    assert len(psnap["elements"]) > 0
    assert isinstance(psnap["pieces"], list)
    assert len(psnap["pieces"]) >= 2  # at least front + back
    assert psnap["measurements"]["waist"] == m.waist_cm
    assert psnap["measurements"]["hip"] == m.hip_cm


def test_psnap_elements_have_required_fields():
    from app.patterns.engine import generate_pattern
    m = _meas()
    psnap = generate_pattern(_features("a_line"), m)
    for elem in psnap["elements"]:
        assert "id" in elem
        assert "type" in elem
        assert elem["type"] in ("line", "curve", "grain-line")
        if elem["type"] == "line":
            assert "start" in elem and "end" in elem
            assert "isFold" in elem
        if elem["type"] == "curve":
            assert "start" in elem and "end" in elem
            assert "cp1" in elem and "cp2" in elem


def test_psnap_pieces_have_required_fields():
    from app.patterns.engine import generate_pattern
    m = _meas()
    psnap = generate_pattern(_features("pencil"), m)
    for piece in psnap["pieces"]:
        assert "id" in piece
        assert "name" in piece
        assert "elementIds" in piece
        assert isinstance(piece["elementIds"], list)
        assert len(piece["elementIds"]) > 0
        assert piece["closed"] is True
