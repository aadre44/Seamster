"""Tests for vision-contour patternization + tier 5 wiring: cleanup pipeline,
scaling, source flags, LLM-fallback exclusion, synonym store lookup, and the
save-as-template endpoint (user-edit feedback loop).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.patterns.engine as eng
from app.main import app
from app.models.features import (
    ClosureFeature,
    ContourPoint,
    GarmentFeatures,
    GarmentType,
    PieceContour,
)
from app.models.measurements import Measurements
from app.patterns.learned_pieces import PieceTemplate, TemplateStore, apply_template
from app.patterns.vision_contours import (
    MIN_CONTOUR_CONFIDENCE,
    generate_vision_pieces,
    patternize_contour,
)

M = Measurements(
    waist_cm=76, hip_cm=94, waist_to_hip_cm=21, length_cm=65,
    chest_cm=90, shoulder_width_cm=38, arm_length_cm=60,
)


def contour(**over) -> PieceContour:
    base = dict(
        detail="cascade_panel",
        name="Cascade Panel",
        points=[
            ContourPoint(x=0.0, y=0.0),
            ContourPoint(x=1.0, y=0.0),
            ContourPoint(x=1.0, y=1.4),
            ContourPoint(x=0.0, y=1.4),
        ],
        width_frac=0.25,
        reference="chest_cm",
        cut_qty=2,
        confidence=0.8,
    )
    base.update(over)
    return PieceContour(**base)


def features(**over) -> GarmentFeatures:
    base = dict(
        garment_type=GarmentType.SKIRT,
        silhouette="straight",
        length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        details=[],
        confidence=0.9,
    )
    base.update(over)
    return GarmentFeatures(**base)


# ── patternize_contour ────────────────────────────────────────────────────────

def test_scale_comes_from_width_frac_times_reference():
    spec = patternize_contour(contour(), M)
    xs = [p.x for p in spec.outline]
    ys = [p.y for p in spec.outline]
    assert max(xs) - min(xs) == pytest.approx(90 * 0.25)       # chest_cm * width_frac
    assert max(ys) - min(ys) == pytest.approx(90 * 0.25 * 1.4)  # aspect preserved
    assert spec.source == "vision"
    assert spec.detail == "cascade_panel"
    assert spec.cut_qty == 2


def test_unknown_reference_falls_back_to_chest():
    spec = patternize_contour(contour(reference="femur_cm"), M)
    xs = [p.x for p in spec.outline]
    assert max(xs) - min(xs) == pytest.approx(90 * 0.25)


def test_low_confidence_contour_rejected():
    with pytest.raises(ValueError, match="confidence"):
        patternize_contour(contour(confidence=MIN_CONTOUR_CONFIDENCE - 0.05), M)


def test_too_few_points_rejected():
    with pytest.raises(ValueError, match="points"):
        patternize_contour(
            contour(points=[ContourPoint(x=0, y=0), ContourPoint(x=1, y=0)]), M
        )


def test_tiny_scale_rejected_as_noise():
    with pytest.raises(ValueError, match="noise"):
        patternize_contour(contour(width_frac=0.001), M)  # clamps to 3% but height*aspect…


def test_nearly_vertical_edges_are_snapped_straight():
    wobbly = contour(points=[
        ContourPoint(x=0.0, y=0.0),
        ContourPoint(x=1.0, y=0.02),   # ~1° off horizontal → snapped
        ContourPoint(x=1.03, y=1.0),   # ~2° off vertical → snapped
        ContourPoint(x=0.0, y=1.0),
    ])
    spec = patternize_contour(wobbly, M)
    xs = sorted({round(p.x, 3) for p in spec.outline})
    ys = sorted({round(p.y, 3) for p in spec.outline})
    assert len(xs) == 2 and len(ys) == 2  # a clean rectangle after snapping


def test_near_symmetric_contour_is_symmetrized():
    lopsided = contour(points=[
        ContourPoint(x=0.5, y=0.0),    # apex
        ContourPoint(x=1.0, y=1.0),    # right corner
        ContourPoint(x=0.04, y=1.0),   # left corner, slightly off-mirror
    ])
    spec = patternize_contour(lopsided, M)
    xs = [p.x for p in spec.outline]
    ys = [p.y for p in spec.outline]
    apex = min(spec.outline, key=lambda p: p.y)
    cx = (min(xs) + max(xs)) / 2
    assert apex.x == pytest.approx(cx, abs=0.05)
    corners = sorted(p.x for p in spec.outline if p.y == max(ys))
    assert corners[0] + corners[1] == pytest.approx(2 * cx, abs=0.05)


def test_attachment_edges_carry_label():
    spec = patternize_contour(
        contour(attachment_label="hem", attachment_edges=[0]), M
    )
    assert spec.edge_labels == {0: "hem"}


def test_invalid_attachment_label_dropped():
    spec = patternize_contour(
        contour(attachment_label="elbow", attachment_edges=[0]), M
    )
    assert spec.edge_labels == {}


def test_generate_vision_pieces_skips_bad_keeps_good():
    f = features(piece_contours=[
        contour(),                                   # valid
        contour(detail="junk", confidence=0.1),      # rejected: confidence
    ])
    specs = generate_vision_pieces(f, M)
    assert [s.detail for s in specs] == ["cascade_panel"]


def test_notion_contour_rejected():
    with pytest.raises(ValueError, match="notion"):
        patternize_contour(
            contour(detail="frog_button_closure", name="Chinese Frog Button / Knot Closure"),
            M,
        )


def test_square_bounding_box_rejected():
    unit_square = [
        ContourPoint(x=0.0, y=0.0), ContourPoint(x=1.0, y=0.0),
        ContourPoint(x=1.0, y=1.0), ContourPoint(x=0.0, y=1.0),
    ]
    with pytest.raises(ValueError, match="bounding box"):
        patternize_contour(contour(points=unit_square), M)


def test_strip_rectangle_still_accepted():
    # A genuinely rectangular piece (collar stand / binding strip) has a strip-like
    # aspect and must NOT be caught by the square-bounding-box guard.
    strip = [
        ContourPoint(x=0.0, y=0.0), ContourPoint(x=1.0, y=0.0),
        ContourPoint(x=1.0, y=0.12), ContourPoint(x=0.0, y=0.12),
    ]
    spec = patternize_contour(contour(points=strip, width_frac=0.35), M)
    ys = [p.y for p in spec.outline]
    assert max(ys) - min(ys) == pytest.approx(90 * 0.35 * 0.12)


def test_generate_vision_pieces_dedupes_against_engine_pieces():
    f = features(piece_contours=[
        contour(detail="back_panel", name="Back Panel"),     # engine drafted the back
        contour(),                                           # genuinely novel: kept
    ])
    specs = generate_vision_pieces(f, M, existing_names={"Back Bodice", "Overlap Front"})
    assert [s.detail for s in specs] == ["cascade_panel"]


# ── engine wiring ─────────────────────────────────────────────────────────────

def test_vision_pieces_appended_with_source_and_detail():
    psnap = eng.generate_pattern(features(piece_contours=[contour()]), M)
    cascade = next(p for p in psnap["pieces"] if p["name"] == "Cascade Panel")
    assert cascade["source"] == "vision"
    assert cascade["detail"] == "cascade_panel"
    # native pieces stay engine-sourced
    front = next(p for p in psnap["pieces"] if "Front" in p["name"])
    assert front["source"] == "engine"


def test_contour_detail_excluded_from_llm_fallback(monkeypatch):
    seen: list[list[str]] = []

    def fake_generate(unsupported, feats, m, edge_runs=None):
        seen.append(list(unsupported))
        return []

    monkeypatch.setattr(eng, "generate_novel_pieces", fake_generate)
    f = features(
        details=["cascade_panel", "mystery_trim"],
        piece_contours=[contour()],  # covers cascade_panel
    )
    eng.generate_pattern(f, M)
    assert seen == [["mystery_trim"]]


# ── synonym-aware template lookup ─────────────────────────────────────────────

def test_store_find_matches_synonyms_and_plurals(tmp_path):
    store = TemplateStore(path=tmp_path / "learned.json")
    store.add(PieceTemplate(
        id="cargo_pocket-pants-v1", trigger_detail="cargo_pocket",
        garment_types=["pants"], name="Cargo Pocket", description="",
        geometry="rectangle", length_formula="20.0", width_formula="16.0",
    ))
    assert store.find("cargo_pockets", "pants") is not None      # plural
    assert store.find("utility_pocket", "pants") is not None     # synonym
    assert store.find("pocket_cargo", "pants") is not None       # token order
    assert store.find("welt_pocket", "pants") is None            # different piece
    assert store.find("utility_pocket", "skirt") is None         # wrong garment


# ── save-as-template endpoint ─────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.api.templates as tpl_api

    store = TemplateStore(path=tmp_path / "learned.json")
    monkeypatch.setattr(tpl_api, "get_store", lambda: store)
    return TestClient(app), store


def test_save_template_roundtrip(client):
    http, store = client
    resp = http.post("/api/templates", json={
        "trigger_detail": "cascade_panel",
        "garment_type": "skirt",
        "name": "Cascade Panel",
        "cut_qty": 2,
        "outline": [
            {"x": 0.0, "y": 0.0},
            {"x": 20.0, "y": 0.0},
            {"x": 20.0, "y": 30.0},
            {"x": 0.0, "y": 30.0},
        ],
        "reference": "waist_cm",
        "reference_value": 76.0,
    })
    assert resp.status_code == 200, resp.text
    saved = store.find("cascade_panel", "skirt")
    assert saved is not None and saved.geometry == "custom"

    # the corrected shape re-scales for a different body
    bigger = Measurements(waist_cm=95, hip_cm=110, waist_to_hip_cm=22, length_cm=70)
    spec = apply_template(saved, bigger)
    xs = [v.x for v in spec.outline]
    assert max(xs) - min(xs) == pytest.approx(20.0 * 95 / 76, rel=1e-3)


def test_save_template_replaces_llm_version(client):
    http, store = client
    store.add(PieceTemplate(
        id="cascade_panel-skirt-v1", trigger_detail="cascade_panel",
        garment_types=["skirt"], name="LLM Guess", description="",
        geometry="rectangle", length_formula="30.0", width_formula="10.0",
    ))
    resp = http.post("/api/templates", json={
        "trigger_detail": "cascade_panel", "garment_type": "skirt",
        "name": "Corrected Panel",
        "outline": [{"x": 0, "y": 0}, {"x": 15, "y": 0}, {"x": 8, "y": 25}],
        "reference": "waist_cm", "reference_value": 76.0,
    })
    assert resp.status_code == 200
    saved = store.find("cascade_panel", "skirt")
    assert saved.name == "Corrected Panel" and saved.geometry == "custom"


def test_save_template_rejects_bad_reference_and_outline(client):
    http, _ = client
    base = {
        "trigger_detail": "x", "garment_type": "skirt", "name": "X",
        "outline": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 5, "y": 10}],
        "reference_value": 76.0,
    }
    assert http.post("/api/templates", json={**base, "reference": "femur_cm"}).status_code == 422
    assert http.post(
        "/api/templates",
        json={**base, "reference": "waist_cm",
              "outline": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]},
    ).status_code == 422


# ── prompt exposure ───────────────────────────────────────────────────────────

def test_prompt_documents_contours_and_force_flag():
    from app.vision.prompts import build_system_prompt

    normal = build_system_prompt(GarmentType.SKIRT)
    assert "piece_contours" in normal
    assert "DEBUG MODE" not in normal
    forced = build_system_prompt(GarmentType.SKIRT, force_contours=True)
    assert "DEBUG MODE" in forced and "MANDATORY" in forced
