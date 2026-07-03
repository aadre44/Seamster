"""Tests for garment composition (tier 4): static plans, the join/merge executor,
the LLM planner with validation + one repair re-prompt, and the placeholder-only-
as-last-resort guarantee.
"""
from __future__ import annotations

import json

import pytest

import app.patterns.compositions as comp
import app.patterns.engine as eng
from app.models.features import ClosureFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements

M = Measurements(
    waist_cm=76, hip_cm=94, waist_to_hip_cm=21, length_cm=65,
    chest_cm=90, shoulder_width_cm=38, arm_length_cm=60, inseam_cm=76,
)


def features(gtype: GarmentType, **over) -> GarmentFeatures:
    base = dict(
        garment_type=gtype,
        silhouette="regular",
        length_category="",
        closure=ClosureFeature(type="none", position="center_front"),
        details=[],
        sleeve_length="short",
        neckline="crew",
        confidence=0.9,
    )
    base.update(over)
    return GarmentFeatures(**base)


def _piece_names(psnap: dict) -> set[str]:
    return {p["name"] for p in psnap["pieces"]}


@pytest.fixture()
def no_planner(monkeypatch):
    """Fail the test if the LLM planner is ever consulted (static-plan paths)."""
    def boom(feats):
        pytest.fail("the LLM planner must not be called when a static plan exists")

    monkeypatch.setattr(comp, "_plan_from_llm", boom)


# ── static plans ──────────────────────────────────────────────────────────────

def test_shorts_compose_to_short_trousers(no_planner):
    psnap = eng.generate_pattern(features(GarmentType.SHORTS), M)
    names = _piece_names(psnap)
    assert "notice" not in psnap
    assert any("Front Leg" in n for n in names)
    # shorts stop well above a full-length leg (~inseam + rise)
    max_y = max(pt["y"] for e in psnap["elements"] for pt in (e["start"], e["end"]))
    assert max_y < 60.0


def test_shorts_respect_detected_length(no_planner):
    knee = eng.generate_pattern(features(GarmentType.SHORTS, length_category="knee"), M)
    micro = eng.generate_pattern(features(GarmentType.SHORTS, length_category="micro"), M)

    def leg_len(psnap):
        return max(pt["y"] for e in psnap["elements"] for pt in (e["start"], e["end"]))

    assert leg_len(knee) > leg_len(micro)


def test_coat_composes_to_long_jacket(no_planner):
    psnap = eng.generate_pattern(
        features(GarmentType.COAT, length_category="maxi", sleeve_length="long"), M
    )
    assert "notice" not in psnap
    assert any("Sleeve" in n for n in _piece_names(psnap))


def test_tunic_composes_to_shirt(no_planner):
    psnap = eng.generate_pattern(features(GarmentType.TUNIC), M)
    assert "notice" not in psnap
    names = _piece_names(psnap)
    assert any("Front" in n for n in names) and any("Back" in n for n in names)


def test_jumpsuit_composes_from_two_builders_with_waist_seam(no_planner):
    psnap = eng.generate_pattern(features(GarmentType.JUMPSUIT), M)
    names = _piece_names(psnap)
    assert "notice" not in psnap
    # pieces from both the shirt block and the trouser block
    assert any("Bodice" in n or "Sleeve" in n for n in names)
    assert any("Leg" in n for n in names)

    # the top's hem and the bottom's waist were relabelled into one join seam
    waist_seam = [c for c in psnap["connections"] if c["label"] == "waist_seam"]
    assert waist_seam, "expected waist_seam connections joining top to bottom"
    by_id = {p["id"]: p["name"] for p in psnap["pieces"]}
    joined = {
        by_id[c[end]["pieceId"]] for c in waist_seam for end in ("from", "to")
    }
    assert any("Leg" in n for n in joined)
    assert any("Leg" not in n for n in joined)


def test_romper_bottom_is_short(no_planner):
    romper = eng.generate_pattern(features(GarmentType.ROMPER), M)
    jumpsuit = eng.generate_pattern(features(GarmentType.JUMPSUIT), M)

    def max_leg_y(psnap):
        leg_ids = {p["id"] for p in psnap["pieces"] if "Leg" in p["name"]}
        return max(
            pt["y"]
            for e in psnap["elements"]
            if e.get("pieceId") in leg_ids and e.get("type") in ("line", "curve")
            for pt in (e["start"], e["end"])
        )

    assert max_leg_y(romper) < max_leg_y(jumpsuit)


def test_composed_components_do_not_overlap(no_planner):
    """Each component's layout is shifted right of the previous one."""
    psnap = eng.generate_pattern(features(GarmentType.JUMPSUIT), M)
    leg_ids = {p["id"] for p in psnap["pieces"] if "Leg" in p["name"]}
    top_ids = {p["id"] for p in psnap["pieces"] if "Bodice" in p["name"]}
    top_max_x = max(
        pt["x"] for e in psnap["elements"] if e.get("pieceId") in top_ids
        for pt in (e["start"], e["end"])
    )
    leg_min_x = min(
        pt["x"] for e in psnap["elements"] if e.get("pieceId") in leg_ids
        for pt in (e["start"], e["end"])
    )
    assert leg_min_x > top_max_x


# ── LLM planner ───────────────────────────────────────────────────────────────

_VALID_PLAN = json.dumps({
    "components": [
        {"builder": "shirt", "overrides": {"sleeve_length": "sleeveless"}, "join": None},
        {"builder": "trousers", "overrides": {"closure": "none"}, "join": "waist_seam"},
    ]
})


class SeqLLM:
    def __init__(self, texts: list[str]):
        self.texts = texts
        self.prompts: list[str] = []

    def __call__(self, provider, system, user_text, max_tokens=600, **kw):
        self.prompts.append(user_text)
        reply = self.texts[min(len(self.prompts) - 1, len(self.texts) - 1)]

        class R:
            text = reply

        return R()


def _wire_planner(monkeypatch, texts: list[str]) -> SeqLLM:
    llm = SeqLLM(texts)
    monkeypatch.setattr(comp, "STATIC_PLANS", {})  # force the planner path
    monkeypatch.setattr(comp, "complete_with_retry", llm)
    monkeypatch.setattr(comp, "get_provider", lambda: object())
    return llm


def test_planner_valid_plan_executes(monkeypatch):
    llm = _wire_planner(monkeypatch, [_VALID_PLAN])
    psnap = comp.compose_pattern(features(GarmentType.JUMPSUIT), M)
    assert psnap is not None
    assert len(llm.prompts) == 1
    names = {p["name"] for p in psnap["pieces"]}
    assert any("Leg" in n for n in names)
    assert any(c["label"] == "waist_seam" for c in psnap["connections"])


def test_planner_invalid_plan_is_repaired_once(monkeypatch):
    bad = json.dumps({"components": [{"builder": "spaceship", "join": None}]})
    llm = _wire_planner(monkeypatch, [bad, _VALID_PLAN])
    psnap = comp.compose_pattern(features(GarmentType.JUMPSUIT), M)
    assert psnap is not None
    assert len(llm.prompts) == 2
    assert "REJECTED" in llm.prompts[1]
    assert "spaceship" in llm.prompts[1]


def test_planner_exhausted_returns_none_then_placeholder(monkeypatch):
    bad = json.dumps({"components": [{"builder": "spaceship", "join": None}]})
    llm = _wire_planner(monkeypatch, [bad, bad])
    assert comp.compose_pattern(features(GarmentType.JUMPSUIT), M) is None
    assert len(llm.prompts) == 2

    # engine falls back to the placeholder ONLY now that composition failed
    monkeypatch.setattr(eng, "detect_unsupported_details", lambda f: [])
    psnap = eng.generate_pattern(features(GarmentType.JUMPSUIT), M)
    assert psnap["pieces"] == []
    assert "notice" in psnap


def test_planner_provider_down_returns_none(monkeypatch):
    from app.llm import LLMError

    def boom(*a, **k):
        raise LLMError("down")

    monkeypatch.setattr(comp, "STATIC_PLANS", {})
    monkeypatch.setattr(comp, "complete_with_retry", boom)
    monkeypatch.setattr(comp, "get_provider", lambda: object())
    assert comp.compose_pattern(features(GarmentType.JUMPSUIT), M) is None


def test_validate_plan_rules():
    ok, errs = comp._validate_plan(json.loads(_VALID_PLAN))
    assert ok is not None and errs == []

    _, errs = comp._validate_plan({"components": []})
    assert errs

    _, errs = comp._validate_plan({"components": [
        {"builder": "shirt", "join": "waist_seam"},
    ]})
    assert any("first component" in e for e in errs)

    _, errs = comp._validate_plan({"components": [
        {"builder": "shirt", "overrides": {"hyperdrive": "on"}, "join": None},
    ]})
    assert any("hyperdrive" in e for e in errs)

    _, errs = comp._validate_plan({"components": [
        {"builder": "shirt", "join": "shoulder_weld"},
    ]})
    assert any("join" in e for e in errs)


# ── registry hygiene ──────────────────────────────────────────────────────────

def test_composed_types_inherit_component_detail_registries():
    from app.patterns.llm_fallback import (
        _PARAMETRIC_DETAILS,
        _SHIRT_DETAILS,
        _TROUSER_DETAILS,
    )

    assert _TROUSER_DETAILS <= _PARAMETRIC_DETAILS["shorts"]
    assert _SHIRT_DETAILS <= _PARAMETRIC_DETAILS["tunic"]
    assert (_SHIRT_DETAILS | _TROUSER_DETAILS) <= _PARAMETRIC_DETAILS["jumpsuit"]
    assert (_SHIRT_DETAILS | _TROUSER_DETAILS) <= _PARAMETRIC_DETAILS["romper"]
