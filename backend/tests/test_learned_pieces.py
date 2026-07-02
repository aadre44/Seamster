"""Tests for the learned-template geometry primitives (novel-piece tier 1).

Covers every geometry apply_template can assemble, the safety fallbacks, the
store round-trip of the new fields, and the llm_fallback plumbing that fills
them from a (mocked) LLM response.
"""
from __future__ import annotations

import json
import math

import pytest

from app.models.features import ClosureFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point, cubic_bezier_length
from app.patterns.learned_pieces import (
    VALID_GEOMETRIES,
    PieceTemplate,
    TemplateStore,
    apply_template,
)

M = Measurements(
    waist_cm=76, hip_cm=94, waist_to_hip_cm=21, length_cm=65,
    chest_cm=90, shoulder_width_cm=38, arm_length_cm=60,
)


def make_template(**over) -> PieceTemplate:
    base = dict(
        id="t-test-v1",
        trigger_detail="test_detail",
        garment_types=["skirt"],
        name="Test Piece",
        description="a test piece",
        geometry="rectangle",
        length_formula="20.0",
        width_formula="10.0",
    )
    base.update(over)
    return PieceTemplate(**base)


def _bbox(outline):
    xs = [v.x for v in outline]
    ys = [v.y for v in outline]
    return min(xs), min(ys), max(xs), max(ys)


def _curve_len(prev, seg: CurveSegment) -> float:
    return cubic_bezier_length(
        Point(prev.x, prev.y), seg.cp1, seg.cp2, Point(seg.x, seg.y)
    )


# ── rectangle (unchanged behaviour) ───────────────────────────────────────────

def test_rectangle_vertical_grain():
    spec = apply_template(make_template(), M)
    assert len(spec.outline) == 4
    assert all(isinstance(v, Point) for v in spec.outline)
    x0, y0, x1, y1 = _bbox(spec.outline)
    assert (x1 - x0, y1 - y0) == (10.0, 20.0)  # width along X, length along Y
    assert spec.grain_start.x == spec.grain_end.x  # vertical grain


def test_rectangle_horizontal_grain():
    spec = apply_template(make_template(grain_direction="width"), M)
    x0, y0, x1, y1 = _bbox(spec.outline)
    assert (x1 - x0, y1 - y0) == (20.0, 10.0)  # length along X
    assert spec.grain_start.y == spec.grain_end.y  # horizontal grain


def test_unknown_geometry_falls_back_to_rectangle():
    spec = apply_template(make_template(geometry="dodecahedron"), M)
    assert len(spec.outline) == 4
    assert all(isinstance(v, Point) for v in spec.outline)


def test_non_positive_dimension_raises():
    with pytest.raises(ValueError):
        apply_template(make_template(length_formula="0.0"), M)
    with pytest.raises(ValueError):
        apply_template(make_template(width_formula="10.0 - 20.0"), M)


# ── trapezoid ─────────────────────────────────────────────────────────────────

def test_trapezoid_honours_top_width():
    spec = apply_template(
        make_template(geometry="trapezoid", top_width_formula="4.0"), M
    )
    top = sorted(v.x for v in spec.outline if v.y == 0.0)
    bottom = sorted(v.x for v in spec.outline if v.y == 20.0)
    assert top[1] - top[0] == pytest.approx(4.0)
    assert bottom[1] - bottom[0] == pytest.approx(10.0)
    # both edges centred in the bounding box
    assert (top[0] + top[1]) / 2 == pytest.approx((bottom[0] + bottom[1]) / 2)


def test_trapezoid_default_top_width_is_half():
    spec = apply_template(make_template(geometry="trapezoid"), M)
    top = sorted(v.x for v in spec.outline if v.y == 0.0)
    assert top[1] - top[0] == pytest.approx(5.0)


def test_trapezoid_formula_scales_with_measurements():
    spec = apply_template(
        make_template(
            geometry="trapezoid",
            width_formula="waist_cm / 4",
            top_width_formula="waist_cm / 8",
        ),
        M,
    )
    bottom = sorted(v.x for v in spec.outline if v.y == 20.0)
    assert bottom[1] - bottom[0] == pytest.approx(76 / 4)


# ── godet ─────────────────────────────────────────────────────────────────────

def test_godet_sides_match_slit_length():
    spec = apply_template(
        make_template(geometry="godet", length_formula="30.0", width_formula="20.0"), M
    )
    apex, right, hem = spec.outline
    assert isinstance(hem, CurveSegment)
    # both straight sides measure exactly the slit length
    left = Point(hem.x, hem.y)
    assert apex.distance_to(Point(right.x, right.y)) == pytest.approx(30.0, abs=1e-6)
    assert apex.distance_to(left) == pytest.approx(30.0, abs=1e-6)
    # apex centred at the top, hem arc dips below the corner chord
    assert apex.y == 0.0
    assert hem.cp1.y > right.y


def test_godet_clamps_oversized_hem():
    spec = apply_template(
        make_template(geometry="godet", length_formula="20.0", width_formula="100.0"), M
    )
    x0, _, x1, _ = _bbox(spec.outline)
    assert x1 - x0 <= 1.8 * 20.0 + 1e-6


# ── circular flounces ─────────────────────────────────────────────────────────

def test_quarter_circle_inner_arc_matches_attachment_edge():
    spec = apply_template(
        make_template(geometry="quarter_circle", length_formula="40.0", width_formula="12.0"), M
    )
    # outline = [inner start, inner arc CurveSegment, outer start, outer arc CurveSegment]
    assert isinstance(spec.outline[1], CurveSegment)
    inner_len = _curve_len(spec.outline[0], spec.outline[1])
    assert inner_len == pytest.approx(40.0, rel=0.02)
    # everything in the +x/+y quadrant
    x0, y0, _, _ = _bbox(spec.outline)
    assert x0 >= -1e-9 and y0 >= -1e-9


def test_half_circle_inner_arc_matches_attachment_edge():
    spec = apply_template(
        make_template(geometry="half_circle", length_formula="60.0", width_formula="15.0"), M
    )
    # 180° sweep → two bezier segments per arc
    segs = [v for v in spec.outline if isinstance(v, CurveSegment)]
    assert len(segs) == 4
    inner_len = _curve_len(spec.outline[0], spec.outline[1]) + _curve_len(
        spec.outline[1], spec.outline[2]
    )
    assert inner_len == pytest.approx(60.0, rel=0.02)
    x0, y0, _, _ = _bbox(spec.outline)
    assert x0 >= -1e-9 and y0 >= -1e-9


def test_flounce_depth_sets_outer_radius():
    spec = apply_template(
        make_template(geometry="quarter_circle", length_formula="40.0", width_formula="12.0"), M
    )
    inner_r = 40.0 / (math.pi / 2)
    _, _, x1, y1 = _bbox(spec.outline)
    assert max(x1, y1) == pytest.approx(inner_r + 12.0, rel=0.01)


# ── curved band ───────────────────────────────────────────────────────────────

def test_curved_band_bows_by_curve_depth():
    spec = apply_template(
        make_template(
            geometry="curved_band",
            length_formula="45.0", width_formula="6.0", curve_depth_formula="3.0",
        ),
        M,
    )
    segs = [v for v in spec.outline if isinstance(v, CurveSegment)]
    assert len(segs) == 2
    # cubic through-midpoint controls sit at 4/3 of the rise
    assert segs[0].cp1.y == pytest.approx(3.0 * 4 / 3)
    # band ends are `width` tall
    ys_at_0 = sorted(v.y for v in spec.outline if v.x in (0.0, 45.0) and isinstance(v, Point))
    assert ys_at_0[-1] - ys_at_0[0] == pytest.approx(6.0)


def test_curved_band_default_depth():
    spec = apply_template(
        make_template(geometry="curved_band", length_formula="45.0", width_formula="6.0"), M
    )
    segs = [v for v in spec.outline if isinstance(v, CurveSegment)]
    assert segs[0].cp1.y == pytest.approx(45.0 * 0.12 * 4 / 3)


# ── shaped rectangle ──────────────────────────────────────────────────────────

def test_shaped_rectangle_pointed_end():
    spec = apply_template(
        make_template(
            geometry="shaped_rectangle", end_shape="pointed",
            length_formula="15.0", width_formula="12.0", cut_qty=3, on_fold=True,
        ),
        M,
    )
    assert len(spec.outline) == 5  # rectangle + centre apex
    apex = max(spec.outline, key=lambda v: v.y)
    assert apex.x == pytest.approx(6.0)
    assert apex.y > 15.0  # apex drops below the straight side corners
    assert spec.cut_qty == 3
    assert spec.on_fold is True
    assert spec.name == "Test Piece"


def test_shaped_rectangle_unknown_shape_falls_back_to_square():
    spec = apply_template(
        make_template(geometry="shaped_rectangle", end_shape="zigzag"), M
    )
    assert len(spec.outline) == 4


# ── template store round-trip ─────────────────────────────────────────────────

def test_new_fields_roundtrip_through_store(tmp_path):
    path = tmp_path / "learned.json"
    store = TemplateStore(path=path)
    store.add(make_template(
        geometry="trapezoid",
        top_width_formula="waist_cm / 8",
        curve_depth_formula="2.0",
        end_shape="rounded",
    ))
    reloaded = TemplateStore(path=path).find("test_detail", "skirt")
    assert reloaded is not None
    assert reloaded.geometry == "trapezoid"
    assert reloaded.top_width_formula == "waist_cm / 8"
    assert reloaded.curve_depth_formula == "2.0"
    assert reloaded.end_shape == "rounded"


def test_legacy_template_without_new_fields_still_loads(tmp_path):
    path = tmp_path / "learned.json"
    legacy = {
        "pieces": [{
            "id": "belt-skirt-v1", "trigger_detail": "belt", "garment_types": ["skirt"],
            "name": "Belt", "description": "", "geometry": "rectangle",
            "length_formula": "waist_cm + 10", "width_formula": "4.0",
        }]
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    t = TemplateStore(path=path).find("belt", "skirt")
    assert t is not None
    assert t.top_width_formula is None
    assert t.end_shape == "square"
    spec = apply_template(t, M)
    assert len(spec.outline) == 4


# ── llm_fallback plumbing ─────────────────────────────────────────────────────

def _fake_features() -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.SKIRT,
        silhouette="a_line",
        length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        details=["cascading_flounce"],
        confidence=0.9,
    )


def test_system_prompt_documents_every_geometry():
    from app.patterns.llm_fallback import _SYSTEM_PROMPT

    for geometry in VALID_GEOMETRIES:
        assert geometry in _SYSTEM_PROMPT, f"{geometry} missing from the LLM prompt"


def test_generate_novel_pieces_plumbs_new_fields(tmp_path, monkeypatch):
    import app.patterns.llm_fallback as fb

    store = TemplateStore(path=tmp_path / "learned.json")
    llm_json = json.dumps({
        "pieces": [{
            "name": "Cascade Flounce",
            "description": "circular cascade flounce",
            "geometry": "quarter_circle",
            "length_formula": "length_cm",
            "width_formula": "18.0",
            "cut_qty": 1,
            "on_fold": False,
            "seam_allowance_formula": "seam_allowance_cm",
            "grain_direction": "length",
        }]
    })

    class FakeResponse:
        text = llm_json

    monkeypatch.setattr(fb, "get_store", lambda: store)
    monkeypatch.setattr(fb, "get_provider", lambda: object())
    monkeypatch.setattr(fb, "complete_with_retry", lambda *a, **k: FakeResponse())

    specs = fb.generate_novel_pieces(["cascading_flounce"], _fake_features(), M)
    assert len(specs) == 1
    assert any(isinstance(v, CurveSegment) for v in specs[0].outline)
    saved = store.find("cascading_flounce", "skirt")
    assert saved is not None and saved.geometry == "quarter_circle"


def test_failed_apply_does_not_persist_template(tmp_path, monkeypatch):
    import app.patterns.llm_fallback as fb

    store = TemplateStore(path=tmp_path / "learned.json")
    llm_json = json.dumps({
        "pieces": [{
            "name": "Broken Piece",
            "geometry": "rectangle",
            "length_formula": "0.0",   # evaluates to a non-positive dimension
            "width_formula": "5.0",
        }]
    })

    class FakeResponse:
        text = llm_json

    monkeypatch.setattr(fb, "get_store", lambda: store)
    monkeypatch.setattr(fb, "get_provider", lambda: object())
    monkeypatch.setattr(fb, "complete_with_retry", lambda *a, **k: FakeResponse())

    specs = fb.generate_novel_pieces(["weird_detail"], _fake_features(), M)
    assert specs == []
    assert store.find("weird_detail", "skirt") is None
