"""Tests for the 'custom' formula-based point-list geometry (novel-piece tier 2)."""
from __future__ import annotations

import json

import pytest

import app.patterns.llm_fallback as fb
from app.models.features import ClosureFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.learned_pieces import PieceTemplate, TemplateStore, apply_template
from app.patterns.novel_validation import validate_spec

M = Measurements(
    waist_cm=76, hip_cm=94, waist_to_hip_cm=21, length_cm=65,
    chest_cm=90, shoulder_width_cm=38, arm_length_cm=60,
)
M_LARGE = Measurements(
    waist_cm=100, hip_cm=120, waist_to_hip_cm=24, length_cm=80,
    chest_cm=110, shoulder_width_cm=44, arm_length_cm=66,
)

# A hood-ish five-sided panel: straight front edge, curved crown, neckline bottom.
_HOOD_POINTS = [
    {"x": "0.0", "y": "0.0"},
    {"x": "chest_cm / 4", "y": "0.0",
     "cp1x": "chest_cm / 12", "cp1y": "0.0 - chest_cm / 20",
     "cp2x": "chest_cm / 6", "cp2y": "0.0 - chest_cm / 20"},
    {"x": "chest_cm / 4", "y": "chest_cm / 3"},
    {"x": "0.0", "y": "chest_cm / 3"},
]


def make_custom(**over) -> PieceTemplate:
    base = dict(
        id="hood-jacket-v1",
        trigger_detail="drawstring_hood",
        garment_types=["jacket"],
        name="Hood Panel",
        description="side hood panel",
        geometry="custom",
        length_formula="chest_cm / 3",
        width_formula="chest_cm / 4",
        points=list(_HOOD_POINTS),
        cut_qty=2,
    )
    base.update(over)
    return PieceTemplate(**base)


def features() -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.JACKET,
        silhouette="regular",
        length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        details=["drawstring_hood"],
        confidence=0.9,
    )


# ── apply_template ────────────────────────────────────────────────────────────

def test_custom_outline_scales_with_measurements():
    small = apply_template(make_custom(), M)
    large = apply_template(make_custom(), M_LARGE)

    def bbox_w(spec):
        xs = [v.x for v in spec.outline]
        return max(xs) - min(xs)

    assert bbox_w(small) == pytest.approx(90 / 4)
    assert bbox_w(large) == pytest.approx(110 / 4)
    assert validate_spec(small, M) == []
    assert validate_spec(large, M_LARGE) == []


def test_custom_bezier_points_become_curve_segments():
    spec = apply_template(make_custom(), M)
    assert any(isinstance(v, CurveSegment) for v in spec.outline)
    # normalised into the +x/+y quadrant despite the negative crown control points
    assert min(v.y for v in spec.outline) >= -1e-9


def test_custom_closing_duplicate_point_is_dropped():
    closed = list(_HOOD_POINTS) + [{"x": "0.0", "y": "0.0"}]
    spec = apply_template(make_custom(points=closed), M)
    assert len(spec.outline) == len(_HOOD_POINTS)


def test_custom_attachment_edges_carry_label():
    spec = apply_template(
        make_custom(attachment_label="neckline", attachment_edges=[2]), M
    )
    assert spec.edge_labels == {2: "neckline"}


def test_custom_without_attachment_edges_has_no_labels():
    spec = apply_template(make_custom(attachment_label="neckline"), M)
    assert spec.edge_labels == {}


@pytest.mark.parametrize("points,message", [
    (None, "at least 3"),
    ([{"x": "0", "y": "0"}, {"x": "5", "y": "0"}], "at least 3"),
    ([{"x": "0"}, {"x": "5", "y": "0"}, {"x": "5", "y": "5"}], "'x' and 'y'"),
])
def test_custom_malformed_points_raise_clear_errors(points, message):
    with pytest.raises(ValueError, match=message):
        apply_template(make_custom(points=points), M)


def test_custom_unsafe_formula_rejected():
    bad = [{"x": "__import__('os').getcwd()", "y": "0"},
           {"x": "5", "y": "0"}, {"x": "5", "y": "5"}]
    with pytest.raises(ValueError, match="Unsafe formula"):
        apply_template(make_custom(points=bad), M)


def test_custom_template_roundtrips_store(tmp_path):
    store = TemplateStore(path=tmp_path / "learned.json")
    store.add(make_custom(attachment_label="neckline", attachment_edges=[2]))
    reloaded = TemplateStore(path=tmp_path / "learned.json").find(
        "drawstring_hood", "jacket"
    )
    assert reloaded is not None
    assert reloaded.points == _HOOD_POINTS
    assert reloaded.attachment_edges == [2]
    spec = apply_template(reloaded, M)
    assert len(spec.outline) == 4


# ── repair-loop integration ───────────────────────────────────────────────────

class SeqLLM:
    def __init__(self, texts):
        self.texts = texts
        self.prompts = []

    def __call__(self, provider, system, user_text, max_tokens=1024, **kw):
        self.prompts.append(user_text)
        reply = self.texts[min(len(self.prompts) - 1, len(self.texts) - 1)]

        class R:
            text = reply

        return R()


def test_malformed_custom_piece_triggers_repair_loop(tmp_path, monkeypatch):
    bad = json.dumps({"pieces": [{
        "name": "Hood Panel", "geometry": "custom",
        "length_formula": "30.0", "width_formula": "22.0",
        "points": [{"x": "0", "y": "0"}, {"x": "22", "y": "0"}],  # only 2 points
    }]})
    good = json.dumps({"pieces": [{
        "name": "Hood Panel", "geometry": "custom",
        "length_formula": "chest_cm / 3", "width_formula": "chest_cm / 4",
        "points": _HOOD_POINTS, "cut_qty": 2,
    }]})
    llm = SeqLLM([bad, good])
    store = TemplateStore(path=tmp_path / "learned.json")
    monkeypatch.setattr(fb, "complete_with_retry", llm)
    monkeypatch.setattr(fb, "get_provider", lambda: object())
    monkeypatch.setattr(fb, "get_store", lambda: store)

    specs = fb.generate_novel_pieces(["drawstring_hood"], features(), M)
    assert len(llm.prompts) == 2
    assert "at least 3" in llm.prompts[1]
    assert len(specs) == 1
    saved = store.find("drawstring_hood", "jacket")
    assert saved is not None and saved.geometry == "custom"


def test_prompt_documents_custom_geometry():
    assert "custom" in fb._SYSTEM_PROMPT
    assert "points" in fb._SYSTEM_PROMPT
    assert "attachment_edges" in fb._SYSTEM_PROMPT
