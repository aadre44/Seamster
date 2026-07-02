"""Tests for novel-piece validation + repair (tier 3): geometric checks,
attachment-edge labelling, the re-prompt loop, arc auto-scaling, the placeholder
fallback, and assembly wiring through _compute_connections.
"""
from __future__ import annotations

import json

import pytest

import app.patterns.engine as eng
import app.patterns.llm_fallback as fb
from app.models.features import ClosureFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point, cubic_bezier_length
from app.patterns.learned_pieces import PieceTemplate, TemplateStore, apply_template
from app.patterns.novel_validation import sample_outline, self_intersects, validate_spec
from app.patterns.skirts import PieceSpec

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


def skirt_features(details: list[str] | None = None) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.SKIRT,
        silhouette="straight",
        length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        details=details or [],
        confidence=0.9,
    )


def _rect_spec(w: float, h: float) -> PieceSpec:
    return PieceSpec(
        name="Rect",
        outline=[Point(0, 0), Point(w, 0), Point(w, h), Point(0, h)],
        darts=[],
        grain_start=Point(w / 2, h * 0.1),
        grain_end=Point(w / 2, h * 0.9),
    )


# ── validate_spec ─────────────────────────────────────────────────────────────

def test_valid_rectangle_passes():
    assert validate_spec(_rect_spec(10, 20), M) == []


def test_degenerately_small_piece_fails():
    problems = validate_spec(_rect_spec(0.2, 10), M)
    assert any("small" in p for p in problems)


def test_implausibly_large_piece_fails():
    problems = validate_spec(_rect_spec(10, 500), M)
    assert any("large" in p for p in problems)


def test_self_intersecting_outline_fails():
    bowtie = PieceSpec(
        name="Bowtie",
        outline=[Point(0, 0), Point(10, 10), Point(10, 0), Point(0, 10)],
        darts=[],
        grain_start=Point(5, 1),
        grain_end=Point(5, 9),
    )
    problems = validate_spec(bowtie, M)
    assert any("self-intersects" in p for p in problems)


def test_every_tier1_geometry_validates_clean():
    for geometry in ("rectangle", "shaped_rectangle", "trapezoid", "godet",
                     "quarter_circle", "half_circle", "curved_band"):
        spec = apply_template(make_template(geometry=geometry), M)
        assert validate_spec(spec, M) == [], f"{geometry} failed its own validation"


def test_sample_outline_flattens_beziers():
    spec = apply_template(make_template(geometry="quarter_circle"), M)
    pts = sample_outline(spec.outline)
    assert len(pts) > len(spec.outline)  # curves contribute sampled points
    assert not self_intersects(pts)


# ── attachment edge labels ────────────────────────────────────────────────────

@pytest.mark.parametrize("geometry,expected_edges", [
    ("rectangle", {0}),
    ("shaped_rectangle", {0}),
    ("trapezoid", {0}),
    ("godet", {0, 2}),
    ("quarter_circle", {0}),
    ("half_circle", {0, 1}),
    ("curved_band", {0}),
])
def test_attachment_label_marks_intrinsic_edges(geometry, expected_edges):
    spec = apply_template(make_template(geometry=geometry, attachment_label="hem"), M)
    assert set(spec.edge_labels.keys()) == expected_edges
    assert set(spec.edge_labels.values()) == {"hem"}


def test_unknown_attachment_label_is_dropped():
    spec = apply_template(make_template(attachment_label="elbow"), M)
    assert spec.edge_labels == {}


def test_no_attachment_label_means_no_edge_labels():
    spec = apply_template(make_template(geometry="quarter_circle"), M)
    assert spec.edge_labels == {}


# ── repair loop ───────────────────────────────────────────────────────────────

_VALID_PIECE = json.dumps({
    "pieces": [{
        "name": "Neck Ruffle",
        "description": "gathered neck ruffle",
        "geometry": "rectangle",
        "length_formula": "waist_cm / 2",
        "width_formula": "8.0",
        "cut_qty": 1,
    }]
})


class SeqLLM:
    """complete_with_retry stand-in that replays canned texts and records prompts."""

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.prompts: list[str] = []

    def __call__(self, provider, system, user_text, max_tokens=1024, **kw):
        self.prompts.append(user_text)
        reply = self.texts[min(len(self.prompts) - 1, len(self.texts) - 1)]

        class R:
            text = reply

        return R()


def _wire(monkeypatch, tmp_path, texts: list[str]) -> tuple[SeqLLM, TemplateStore]:
    llm = SeqLLM(texts)
    store = TemplateStore(path=tmp_path / "learned.json")
    monkeypatch.setattr(fb, "complete_with_retry", llm)
    monkeypatch.setattr(fb, "get_provider", lambda: object())
    monkeypatch.setattr(fb, "get_store", lambda: store)
    return llm, store


def test_bad_json_is_repaired_on_second_attempt(tmp_path, monkeypatch):
    llm, store = _wire(monkeypatch, tmp_path, ["this is not json", _VALID_PIECE])
    specs = fb.generate_novel_pieces(["neck_ruffle"], skirt_features(), M)
    assert len(specs) == 1
    assert len(llm.prompts) == 2
    assert "REJECTED" in llm.prompts[1]
    assert "valid JSON" in llm.prompts[1]
    assert store.find("neck_ruffle", "skirt") is not None


def test_invalid_geometry_feeds_problems_into_reprompt(tmp_path, monkeypatch):
    too_big = json.dumps({"pieces": [{
        "name": "Huge Panel", "geometry": "rectangle",
        "length_formula": "500.0", "width_formula": "10.0",
    }]})
    llm, store = _wire(monkeypatch, tmp_path, [too_big, _VALID_PIECE])
    specs = fb.generate_novel_pieces(["weird_panel"], skirt_features(), M)
    assert len(specs) == 1
    assert len(llm.prompts) == 2
    assert "implausibly large" in llm.prompts[1]


def test_exhausted_repairs_emit_placeholder_and_save_nothing(tmp_path, monkeypatch):
    too_big = json.dumps({"pieces": [{
        "name": "Huge Panel", "geometry": "rectangle",
        "length_formula": "500.0", "width_formula": "10.0",
    }]})
    llm, store = _wire(monkeypatch, tmp_path, [too_big, too_big, too_big])
    specs = fb.generate_novel_pieces(["weird_panel"], skirt_features(), M)
    assert len(llm.prompts) == 3
    assert len(specs) == 1
    assert "placeholder" in specs[0].notes
    assert store.find("weird_panel", "skirt") is None


def test_provider_failure_returns_empty_not_placeholder(tmp_path, monkeypatch):
    from app.llm import LLMError

    def boom(*a, **k):
        raise LLMError("provider down")

    store = TemplateStore(path=tmp_path / "learned.json")
    monkeypatch.setattr(fb, "complete_with_retry", boom)
    monkeypatch.setattr(fb, "get_provider", lambda: object())
    monkeypatch.setattr(fb, "get_store", lambda: store)
    specs = fb.generate_novel_pieces(["neck_ruffle"], skirt_features(), M)
    assert specs == []
    assert store.find("neck_ruffle", "skirt") is None


def test_arc_mismatch_rejected_then_autoscaled_on_final_attempt(tmp_path, monkeypatch):
    flounce = json.dumps({"pieces": [{
        "name": "Hem Flounce", "geometry": "quarter_circle",
        "length_formula": "30.0", "width_formula": "12.0",
        "attachment_label": "hem", "cut_qty": 2,
    }]})
    llm, store = _wire(monkeypatch, tmp_path, [flounce, flounce, flounce])
    specs = fb.generate_novel_pieces(
        ["hem_flounce"], skirt_features(), M, edge_runs={"hem": 60.0}
    )
    # two rejections (mismatch fed back), then the final attempt auto-scales
    assert len(llm.prompts) == 3
    assert "60.0 cm" in llm.prompts[1]
    assert len(specs) == 1
    seg = specs[0].outline[1]
    assert isinstance(seg, CurveSegment)
    inner_len = cubic_bezier_length(
        Point(specs[0].outline[0].x, specs[0].outline[0].y),
        seg.cp1, seg.cp2, Point(seg.x, seg.y),
    )
    assert inner_len == pytest.approx(60.0, rel=0.02)
    saved = store.find("hem_flounce", "skirt")
    assert saved is not None
    assert "* 2.0" in saved.length_formula  # parametric formula, scaled not replaced


def test_arc_within_tolerance_is_accepted_first_try(tmp_path, monkeypatch):
    flounce = json.dumps({"pieces": [{
        "name": "Hem Flounce", "geometry": "quarter_circle",
        "length_formula": "58.0", "width_formula": "12.0",
        "attachment_label": "hem",
    }]})
    llm, store = _wire(monkeypatch, tmp_path, [flounce])
    specs = fb.generate_novel_pieces(
        ["hem_flounce"], skirt_features(), M, edge_runs={"hem": 60.0}
    )
    assert len(llm.prompts) == 1
    assert len(specs) == 1


def test_edge_runs_appear_in_prompt(tmp_path, monkeypatch):
    llm, _ = _wire(monkeypatch, tmp_path, [_VALID_PIECE])
    fb.generate_novel_pieces(
        ["neck_ruffle"], skirt_features(), M, edge_runs={"hem": 52.4, "waist": 19.8}
    )
    assert "hem=52.4" in llm.prompts[0]
    assert "waist=19.8" in llm.prompts[0]
    assert "attachment_label" in fb._SYSTEM_PROMPT


# ── engine wiring ─────────────────────────────────────────────────────────────

def test_edge_run_lengths_from_generated_skirt():
    psnap = eng.generate_pattern(skirt_features(), M)
    runs = eng._edge_run_lengths(psnap)
    assert "hem" in runs and runs["hem"] > 10.0
    assert "waist" in runs and runs["waist"] > 10.0
    assert "side_seam" in runs


def test_novel_piece_with_attachment_label_joins_connections(monkeypatch):
    flounce_template = make_template(
        id="hem_flounce-skirt-v1",
        trigger_detail="hem_flounce",
        name="Hem Flounce",
        geometry="quarter_circle",
        length_formula="40.0",
        width_formula="15.0",
        attachment_label="hem",
    )

    def fake_generate(unsupported, features, measurements, edge_runs=None):
        return [apply_template(flounce_template, measurements)]

    monkeypatch.setattr(eng, "detect_unsupported_details", lambda features: ["hem_flounce"])
    monkeypatch.setattr(eng, "generate_novel_pieces", fake_generate)

    psnap = eng.generate_pattern(skirt_features(), M)
    flounce = next(p for p in psnap["pieces"] if p["name"] == "Hem Flounce")
    hem_conns = [c for c in psnap["connections"] if c["label"] == "hem"]
    assert any(
        flounce["id"] in (c["from"]["pieceId"], c["to"]["pieceId"]) for c in hem_conns
    ), "the flounce's labelled inner arc should pair with the garment hem"
