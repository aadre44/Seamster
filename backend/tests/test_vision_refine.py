"""Tests for the photo-driven refine pass (vision LLM edits drafted outlines)."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

import app.vision.refine as vr
from app.llm import LLMOverloadedError, LLMResponse
from app.main import app
from app.models.features import (
    AsymmetryFeature,
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern
from app.vision.refine import (
    _apply_refinements,
    _pieces_to_compact,
    _validate_entry,
    refine_pattern,
)


def _m() -> Measurements:
    return Measurements(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0,
        chest_cm=90.0, shoulder_width_cm=30.0, arm_length_cm=60.0,
        seam_allowance_cm=1.5,
    )


def _vest_psnap() -> dict:
    feats = GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="button_front", position="center_front"),
        darts=DartFeature(front=0, back=0), neckline="mandarin",
        asymmetry=AsymmetryFeature(front_style="asymmetric_wrap", wrap_side="right",
                                   overlap_cm=18.0, closure_drop_frac=0.15),
        confidence=0.9,
    )
    return generate_pattern(feats, _m())


def _compact_piece(compact: list[dict], name: str) -> dict:
    return next(p for p in compact if p["name"] == name)


# ── Serializer ────────────────────────────────────────────────────────────────

def test_compact_serializer_roundtrips_names_labels_and_curves():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    names = {p["name"] for p in compact}
    assert {"Overlap Front", "Underlap Front", "Back Bodice"} <= names
    ov = _compact_piece(compact, "Overlap Front")
    # Local coords: bbox starts at the origin.
    assert min(pt["x"] for pt in ov["outline"]) == pytest.approx(0.0)
    assert min(pt["y"] for pt in ov["outline"]) == pytest.approx(0.0)
    # Edge labels came through, including the free wrap edge.
    labels = {pt["edge_label"] for pt in ov["outline"]}
    assert {"neckline", "shoulder", "armhole", "side_seam", "hem", "overlap_edge"} <= labels
    # The armscye curve appears as cps on the vertex its edge arrives at: the
    # vertex FOLLOWING the one whose edge_label is "armhole".
    idx = next(i for i, pt in enumerate(ov["outline"]) if pt["edge_label"] == "armhole")
    arriving = ov["outline"][(idx + 1) % len(ov["outline"])]
    assert all(k in arriving for k in ("cp1x", "cp1y", "cp2x", "cp2y"))
    # Ctx captured the piece identity and bbox.
    assert ctx["Overlap Front"].piece_id
    assert ctx["Overlap Front"].width > 20 and ctx["Overlap Front"].height > 40


def _identity_entry(compact_piece: dict, **over) -> dict:
    """A response entry that echoes the drafted outline back unchanged."""
    entry = {
        "name": compact_piece["name"],
        "reason": "test",
        "outline": [dict(pt) for pt in compact_piece["outline"]],
    }
    entry.update(over)
    return entry


# ── Validation guards ─────────────────────────────────────────────────────────

def test_identity_response_validates():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"))
    spec, problems = _validate_entry(entry, ctx, _m())
    assert problems == []
    assert spec is not None and spec.source == "vision" and spec.name == "Overlap Front"


def test_unknown_piece_name_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"), name="Front Thing")
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and "unknown piece" in problems[0]


def test_oversized_bbox_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"))
    for pt in entry["outline"]:
        pt["x"] = pt["x"] * 1.6  # +60% width
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and any("width" in p for p in problems)


def test_dropped_seam_label_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"))
    for pt in entry["outline"]:
        if pt["edge_label"] == "side_seam":
            pt["edge_label"] = ""
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and any("side_seam" in p for p in problems)


def test_runaway_control_point_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"))
    entry["outline"][1].update({"cp1x": 500.0, "cp1y": -400.0, "cp2x": 1.0, "cp2y": 1.0})
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and any("runaway" in p for p in problems)


def test_moved_fold_anchor_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    back = _compact_piece(compact, "Back Bodice")
    assert back["on_fold"] is True
    entry = _identity_entry(back)
    entry["outline"][0]["x"] += 15.0  # drag the fold-edge anchor sideways
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and any("fold" in p or "anchors" in p for p in problems)


def test_explicit_closing_duplicate_is_dropped():
    # Models often close the loop themselves; the duplicate must not create a
    # zero-length edge that trips the self-intersection check (live blueVest bug).
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Overlap Front"))
    first = entry["outline"][0]
    entry["outline"].append({"x": first["x"], "y": first["y"], "edge_label": "overlap_edge"})
    spec, problems = _validate_entry(entry, ctx, _m())
    assert problems == []
    assert len(spec.outline) == len(entry["outline"]) - 1


def test_degenerate_control_points_become_plain_point():
    # cp1 == cp2 == the vertex itself is the model marking a straight edge.
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Underlap Front"))
    pt = entry["outline"][0]
    pt.update({"cp1x": pt["x"], "cp1y": pt["y"], "cp2x": pt["x"], "cp2y": pt["y"]})
    spec, problems = _validate_entry(entry, ctx, _m())
    assert problems == []
    from app.patterns.geometry import CurveSegment
    assert not isinstance(spec.outline[0], CurveSegment)


def test_shortened_structural_seam_rejected():
    """The prompt rule 'structural seams keep their drafted length' is enforced:
    a side seam stretched well past tolerance rejects the piece."""
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _identity_entry(_compact_piece(compact, "Underlap Front"))
    # The waist vertex is the second one leaving a side_seam edge; dragging it far
    # sideways lengthens the seam >12% while the bbox stays within limits.
    side_idxs = [i for i, pt in enumerate(entry["outline"]) if pt["edge_label"] == "side_seam"]
    entry["outline"][side_idxs[1]]["x"] += 14.0
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None
    assert any("side_seam" in p and "sew together" in p for p in problems)


def test_free_edge_reshape_passes_seam_guard():
    """Reshaping a non-structural edge (the wrap closure) must NOT trip the guard."""
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _curved_wrap_entry(compact, ctx)
    spec, problems = _validate_entry(entry, ctx, _m())
    assert problems == []
    assert spec is not None


def test_self_intersecting_outline_rejected():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    name = "Underlap Front"
    labels = [pt["edge_label"] for pt in _compact_piece(compact, name)["outline"]]
    # A bowtie with the original labels sprinkled on so the label guard passes.
    pts = [(0, 0), (20, 30), (20, 0), (0, 30), (10, 50), (5, 55)]
    outline = [
        {"x": x, "y": y, "edge_label": labels[i] if i < len(labels) else ""}
        for i, (x, y) in enumerate(pts)
    ]
    entry = {"name": name, "outline": outline}
    spec, problems = _validate_entry(entry, ctx, _m())
    assert spec is None and problems


# ── Apply ─────────────────────────────────────────────────────────────────────

def _curved_wrap_entry(compact: list[dict], ctx) -> dict:
    """Reshape the Overlap Front's free edge with a bezier (blueVest-style)."""
    ov = _compact_piece(compact, "Overlap Front")
    entry = _identity_entry(ov, reason="wrap edge curves in the photo")
    # Curve the edge arriving at vertex 1 (the neckline curve target).
    p0, p1 = entry["outline"][0], entry["outline"][1]
    p1.update({
        "cp1x": p0["x"] + 2.0, "cp1y": p0["y"] - 1.0,
        "cp2x": p1["x"] - 2.0, "cp2y": p1["y"] + 1.0,
    })
    return entry


def test_apply_replaces_geometry_in_place():
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _curved_wrap_entry(compact, ctx)
    spec, problems = _validate_entry(entry, ctx, _m())
    assert problems == []

    before_ids = {p["name"]: p["id"] for p in psnap["pieces"]}
    before_back_elems = [
        e for e in psnap["elements"]
        if e.get("pieceId") == before_ids["Back Bodice"]
    ]
    updated = _apply_refinements(psnap, {"Overlap Front": spec}, ctx)

    # Original psnap untouched (deep copy).
    assert {p["name"]: p.get("source", "engine") for p in psnap["pieces"]}["Overlap Front"] == "engine"

    pieces = {p["name"]: p for p in updated["pieces"]}
    ov = pieces["Overlap Front"]
    assert ov["id"] == before_ids["Overlap Front"]          # identity kept
    assert ov["source"] == "vision" and ov["detail"] == "photo_refine"
    elems = {e["id"]: e for e in updated["elements"]}
    assert all(eid in elems for eid in ov["elementIds"])
    assert any(elems[eid]["type"] == "curve" for eid in ov["elementIds"])
    # The refined piece stays at its canvas position (bbox min preserved).
    new_min_x = min(elems[eid]["start"]["x"] for eid in ov["elementIds"])
    assert new_min_x == pytest.approx(ctx["Overlap Front"].offset_x, abs=0.2)
    # Untouched pieces are byte-identical.
    after_back_elems = [
        e for e in updated["elements"] if e.get("pieceId") == before_ids["Back Bodice"]
    ]
    assert after_back_elems == before_back_elems
    # Connections recomputed and structural seams still pair.
    labels = {c["label"] for c in updated["connections"]}
    assert "side_seam" in labels and "shoulder" in labels


# ── refine_pattern (fake provider) ────────────────────────────────────────────

def _fake_response(payload: dict | str) -> LLMResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return LLMResponse(text=text)


def _install_fake(monkeypatch, responses: list[dict | str]) -> list[dict]:
    """Monkeypatch the provider call; returns the recorded call kwargs."""
    calls: list[dict] = []

    async def fake_acomplete(provider, **kwargs):
        calls.append(kwargs)
        return _fake_response(responses[min(len(calls) - 1, len(responses) - 1)])

    monkeypatch.setattr(vr, "acomplete_with_retry", fake_acomplete)
    monkeypatch.setattr(vr, "get_provider", lambda: object())
    return calls


async def test_refine_applies_valid_response(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _curved_wrap_entry(compact, ctx)
    calls = _install_fake(monkeypatch, [{"pieces": [entry]}])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert summary["changed"] == ["Overlap Front"]
    assert "Back Bodice" in summary["unchanged"]
    assert summary["rejected"] == []
    assert len(calls) == 1
    pieces = {p["name"]: p for p in updated["pieces"]}
    assert pieces["Overlap Front"]["source"] == "vision"


async def test_refine_empty_response_changes_nothing(monkeypatch):
    psnap = _vest_psnap()
    _install_fake(monkeypatch, [{"pieces": []}])
    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert summary["changed"] == [] and summary["rejected"] == []
    assert updated["pieces"] == psnap["pieces"]


async def test_refine_repairs_then_applies(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    bad = _identity_entry(_compact_piece(compact, "Overlap Front"), name="Wrong Name")
    good = _curved_wrap_entry(compact, ctx)
    calls = _install_fake(monkeypatch, [{"pieces": [bad]}, {"pieces": [good]}])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert len(calls) == 2
    # The repair prompt carried the rejection reason.
    assert "PREVIOUS ATTEMPT WAS REJECTED" in calls[1]["user_text"]
    assert "unknown piece" in calls[1]["user_text"]
    assert summary["changed"] == ["Overlap Front"]


async def test_refine_double_failure_returns_unchanged(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    bad = _identity_entry(_compact_piece(compact, "Overlap Front"), name="Wrong Name")
    calls = _install_fake(monkeypatch, [{"pieces": [bad]}, {"pieces": [bad]}])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert len(calls) == 2
    assert summary["changed"] == []
    assert summary["rejected"] and "unknown piece" in summary["rejected"][0]["reason"]
    assert updated["pieces"] == psnap["pieces"]


async def test_refine_partial_acceptance_on_final_attempt(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    bad = _identity_entry(_compact_piece(compact, "Overlap Front"), name="Wrong Name")
    good = _curved_wrap_entry(compact, ctx)
    calls = _install_fake(monkeypatch, [{"pieces": [bad]}, {"pieces": [bad, good]}])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert summary["changed"] == ["Overlap Front"]      # the valid piece survives
    assert summary["rejected"]                          # the bad one is reported


async def test_refine_no_pieces_raises(monkeypatch):
    _install_fake(monkeypatch, [{"pieces": []}])
    with pytest.raises(ValueError, match="no pieces"):
        await refine_pattern({"pieces": [], "elements": []}, GarmentType.VEST, _m(), b"png")


# ── Truncated responses ───────────────────────────────────────────────────────

def _install_fake_llm(monkeypatch, responses: list[LLMResponse]) -> list[dict]:
    """Like _install_fake but with full LLMResponse control (truncated flag)."""
    calls: list[dict] = []

    async def fake_acomplete(provider, **kwargs):
        calls.append(kwargs)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(vr, "acomplete_with_retry", fake_acomplete)
    monkeypatch.setattr(vr, "get_provider", lambda: object())
    return calls


async def test_truncated_response_salvages_complete_pieces(monkeypatch):
    """A response cut off at the token limit keeps its complete piece objects
    instead of rejecting everything (the silent-no-change failure of the live
    blueVest run)."""
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    good = _curved_wrap_entry(compact, ctx)
    cut = '{"pieces": [' + json.dumps(good) + ', {"name": "Back Bodice", "outline": [{"x": 0'
    calls = _install_fake_llm(monkeypatch, [LLMResponse(text=cut, truncated=True)])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert summary["changed"] == ["Overlap Front"]
    pieces = {p["name"]: p for p in updated["pieces"]}
    assert pieces["Overlap Front"]["source"] == "vision"
    # Truncation triggers a repair attempt (and the fake stays truncated).
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == vr._MAX_RESPONSE_TOKENS


async def test_truncated_unsalvageable_reprompts_with_reason(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    good = _curved_wrap_entry(compact, ctx)
    calls = _install_fake_llm(monkeypatch, [
        LLMResponse(text='{"pieces": [{"name": "Ove', truncated=True),
        LLMResponse(text=json.dumps({"pieces": [good]})),
    ])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert len(calls) == 2
    assert "cut off at the token limit" in calls[1]["user_text"]
    assert summary["changed"] == ["Overlap Front"]


async def test_salvaged_pieces_survive_a_regressing_repair(monkeypatch):
    """If the repair attempt is worse than the truncated first attempt, the pieces
    already validated are still applied."""
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    good = _curved_wrap_entry(compact, ctx)
    cut = '{"pieces": [' + json.dumps(good) + ', {"name": "Back Bodice", "out'
    _install_fake_llm(monkeypatch, [
        LLMResponse(text=cut, truncated=True),
        LLMResponse(text="sorry, I cannot help with that"),
    ])

    updated, summary = await refine_pattern(psnap, GarmentType.VEST, _m(), b"png")
    assert summary["changed"] == ["Overlap Front"]


# ── Endpoint ──────────────────────────────────────────────────────────────────

_PNG = (  # 1x1 transparent PNG
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfa\xcf\xf0\xbf\x1e\x00"
    b"\x07\x82\x02\x7f=\xc7\xdc\xf7\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _post_refine(client: TestClient, psnap: dict) -> object:
    return client.post("/api/refine", data={
        "garment_type": "vest",
        "psnap": json.dumps(psnap),
        "measurements": _m().model_dump_json(),
    }, files={"front_image": ("front.png", io.BytesIO(_PNG), "image/png")})


def test_endpoint_refines_and_summarizes(monkeypatch):
    psnap = _vest_psnap()
    compact, ctx = _pieces_to_compact(psnap)
    entry = _curved_wrap_entry(compact, ctx)
    _install_fake(monkeypatch, [{"pieces": [entry]}])

    resp = _post_refine(TestClient(app), psnap)
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["changed"] == ["Overlap Front"]
    pieces = {p["name"]: p for p in body["psnap"]["pieces"]}
    assert pieces["Overlap Front"]["source"] == "vision"


def test_endpoint_rejects_malformed_psnap():
    resp = TestClient(app).post("/api/refine", data={
        "garment_type": "vest",
        "psnap": "{not json",
        "measurements": _m().model_dump_json(),
    }, files={"front_image": ("front.png", io.BytesIO(_PNG), "image/png")})
    assert resp.status_code == 422


def test_endpoint_maps_llm_error_to_502(monkeypatch):
    psnap = _vest_psnap()

    async def boom(provider, **kwargs):
        raise LLMOverloadedError("provider down")

    monkeypatch.setattr(vr, "acomplete_with_retry", boom)
    monkeypatch.setattr(vr, "get_provider", lambda: object())
    resp = _post_refine(TestClient(app), psnap)
    assert resp.status_code == 502
