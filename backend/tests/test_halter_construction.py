"""Halter / backless / open-front construction support.

Covers the three orthogonal construction axes added to fix the halter-top miss
(see the green-blouse example): an integral halter strap, a gated/omitted back,
and a deep open centre front — plus the regression that a default (None)
construction reproduces the ordinary shoulder-seam shirt.
"""
from __future__ import annotations

import pytest

from app.models.features import (
    ClosureFeature,
    Construction,
    DartFeature,
    GarmentFeatures,
    GarmentType,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern


def _measurements() -> Measurements:
    return Measurements(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=55.0,
        chest_cm=90.0, shoulder_width_cm=38.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


def _shirt_features(
    *, construction: Construction | None = None, details: list[str] | None = None,
    neckline: str = "v_neck",
) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.SHIRT,
        silhouette="fitted",
        length_category="cropped",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0),
        details=details or [],
        sleeve_length="sleeveless",
        neckline=neckline,
        construction=construction,
        confidence=0.8,
    )


def _names(psnap: dict) -> list[str]:
    return [p["name"] for p in psnap["pieces"]]


def _piece(psnap: dict, name: str) -> dict | None:
    return next((p for p in psnap["pieces"] if p["name"] == name), None)


# ── Halter + backless + deep open front (the green-blouse case) ────────────────

def test_halter_backless_split_front():
    feats = _shirt_features(
        construction=Construction(
            strap_style="halter_neck", back_coverage="backless", front_opening="deep_v_split",
        ),
        details=["spaghetti_straps", "elastic_hem", "tie_front"],
        neckline="halter",
    )
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)

    # Backless → no back bodice at all.
    assert "Back Bodice" not in names

    # ONE continuous front cut on the fold at the back-neck; the centre front is split
    # open in a deep V (the two panels join only via the integral strap).
    front = _piece(psnap, "Front")
    assert front is not None, names
    assert front["onFold"] is True

    # The exposed edges get a facing; the backless top gets a waist tie.
    assert "Front Facing" in names
    assert "Waist Tie" in names

    # elastic_hem builds a native casing band — not an LLM piece.
    assert "Hem Casing Band" in names

    # No stray duplicate strap pieces (the strap is integral to the halter front).
    assert not any("Strap" in n for n in names), names


# ── Regression: pattern 4 — shoulder_seam + plunge must NOT split the front ────

def test_shoulder_seam_plunge_is_one_piece():
    feats = _shirt_features(
        construction=Construction(strap_style="shoulder_seam", back_coverage="full", front_opening="plunge"),
        details=[],
        neckline="v_neck",
    )
    # A standard shoulder-seam top: sleeveless input here, so no sleeve expected.
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)
    front = _piece(psnap, "Front Bodice")
    assert front is not None, names
    assert front["onFold"] is True          # one piece on the fold — no centre-front seam
    assert "Back Bodice" in names
    assert "Sleeve" not in names            # sleeveless input → no sleeve


# ── Strappy non-halter tops: sleeveless, shoulderless, with strap pieces ───────

def test_spaghetti_straps_shoulderless_with_strap_piece():
    feats = _shirt_features(
        construction=Construction(strap_style="spaghetti_straps", back_coverage="low_back", front_opening="plunge"),
        details=[],
        neckline="v_neck",
    )
    # Even if the analysis (wrongly) said long sleeves, a strappy top is sleeveless.
    feats.sleeve_length = "long"
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)

    assert "Sleeve" not in names                       # forced sleeveless
    front = _piece(psnap, "Front")
    assert front is not None and front["onFold"] is True
    assert any("Strap" in n for n in names), names     # real strap pieces produced
    # Shoulderless half-back band: all straight edges, flat top, no shoulder.
    back = _piece(psnap, "Back Bodice")
    assert back is not None
    bids = set(back["elementIds"])
    bedges = [e for e in psnap["elements"] if e["id"] in bids and e["type"] in ("line", "curve")]
    assert all(e["type"] == "line" for e in bedges), "shoulderless back should have no curve"


def test_strapless_band_front_no_straps_no_sleeve():
    feats = _shirt_features(
        construction=Construction(strap_style="strapless", back_coverage="full", front_opening="closed"),
        details=[],
        neckline="strapless",
    )
    feats.sleeve_length = "short"
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)
    assert "Sleeve" not in names
    front = _piece(psnap, "Front")
    assert front is not None and front["onFold"] is True
    assert not any("Strap" in n for n in names), names   # strapless → no strap pieces


# ── Strap width is detected per photo and sizes the strap ──────────────────────

def _front_strap_top_width(psnap: dict) -> float:
    """Width of the halter strap's top edge (the back-neck/strap-top, at minimum y)."""
    front = _piece(psnap, "Front")
    ids = set(front["elementIds"])
    edges = [e for e in psnap["elements"] if e["id"] in ids and e["type"] in ("line", "curve")]
    top_y = min(min(e["start"]["y"], e["end"]["y"]) for e in edges)
    top = next(e for e in edges
               if abs(e["start"]["y"] - top_y) < 0.01 and abs(e["end"]["y"] - top_y) < 0.01)
    return abs(e_x(top, "end") - e_x(top, "start"))


def e_x(edge: dict, end: str) -> float:
    return edge[end]["x"]


def _halter(strap_width, front_opening="deep_v_split"):
    return _shirt_features(
        construction=Construction(strap_style="halter_neck", back_coverage="backless",
                                  front_opening=front_opening, strap_width=strap_width),
        details=[], neckline="halter",
    )


@pytest.mark.parametrize("front_opening", ["deep_v_split", "plunge"])
def test_halter_strap_width_scales_thin_medium_wide(front_opening):
    m = _measurements()
    w_thin = _front_strap_top_width(generate_pattern(_halter("thin", front_opening), m))
    w_med = _front_strap_top_width(generate_pattern(_halter("medium", front_opening), m))
    w_wide = _front_strap_top_width(generate_pattern(_halter("wide", front_opening), m))
    assert w_thin < w_med < w_wide, (w_thin, w_med, w_wide)
    # None falls back to the medium default (no blanket thickening).
    w_none = _front_strap_top_width(generate_pattern(_halter(None, front_opening), m))
    assert abs(w_none - w_med) < 0.01


def test_halter_strap_outer_edge_is_a_gradual_curve():
    psnap = generate_pattern(_halter("wide"), _measurements())
    front = _piece(psnap, "Front")
    ids = set(front["elementIds"])
    # the bust→strap transition is a curve labelled "armhole", not a straight corner
    assert any(e["type"] == "curve" and e.get("seamLabel") == "armhole"
               for e in psnap["elements"] if e["id"] in ids)


def test_strap_width_inferred_from_notes():
    """When the model omits strap_width, it is backfilled from the notes."""
    from app.vision.analyzer import _refine_strap_width

    feats = GarmentFeatures(
        garment_type=GarmentType.BLOUSE, silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0), details=[], sleeve_length="sleeveless",
        neckline="halter",
        construction=Construction(strap_style="halter_neck", back_coverage="backless",
                                  front_opening="deep_v_split", strap_width=None),
        confidence=0.8,
        notes="Halter top; the bust panel flares into a wide, thick strap around the neck.",
    )
    assert _refine_strap_width(feats).construction.strap_width == "wide"


def test_tank_strap_piece_width_scales():
    def strap_w(sw):
        feats = _shirt_features(
            construction=Construction(strap_style="spaghetti_straps", back_coverage="low_back",
                                      front_opening="closed", strap_width=sw),
            details=[], neckline="round",
        )
        psnap = generate_pattern(feats, _measurements())
        strap = next(p for p in psnap["pieces"] if "Strap" in p["name"])
        ids = set(strap["elementIds"])
        xs = [e["start"]["x"] for e in psnap["elements"] if e["id"] in ids and e["type"] == "line"]
        return max(xs) - min(xs)
    assert strap_w("thin") < strap_w("wide")


# ── Tank / cami must NOT be classified as a halter ─────────────────────────────

def test_tank_not_classified_as_halter():
    """A model that returns halter_neck but describes a tank/cami in the notes is corrected
    to spaghetti_straps; a backless guess stays backless (a strap top is never 'full')."""
    from app.vision.analyzer import _refine_strap_style, _clamp_spaghetti_back

    feats = GarmentFeatures(
        garment_type=GarmentType.SHIRT, silhouette="fitted", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=None, details=[], sleeve_length="sleeveless", neckline="round",
        construction=Construction(strap_style="halter_neck", back_coverage="backless",
                                  front_opening="closed"),
        confidence=0.8,
        notes="Sleeveless tank top held up by thin straps over the shoulders.",
    )
    out = _clamp_spaghetti_back(_refine_strap_style(feats))
    assert out.construction.strap_style == "spaghetti_straps"
    assert out.construction.back_coverage == "backless"   # backless is allowed; not forced full


def test_spaghetti_back_cannot_be_full():
    """A spaghetti-strap top with a 'full' back is clamped down to 'low_back' (half back)."""
    from app.vision.analyzer import _clamp_spaghetti_back

    feats = GarmentFeatures(
        garment_type=GarmentType.BLOUSE, silhouette="fitted", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=None, details=[], sleeve_length="sleeveless", neckline="round",
        construction=Construction(strap_style="spaghetti_straps", back_coverage="full",
                                  front_opening="closed"),
        confidence=0.8, notes="Spaghetti-strap cami.",
    )
    out = _clamp_spaghetti_back(feats)
    assert out.construction.back_coverage == "low_back"


def test_true_halter_not_downgraded():
    """A genuine halter (explicit halter neckline, no tank language) is left alone."""
    from app.vision.analyzer import _refine_strap_style

    feats = GarmentFeatures(
        garment_type=GarmentType.SHIRT, silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=None, details=[], sleeve_length="sleeveless", neckline="halter",
        construction=Construction(strap_style="halter_neck", back_coverage="low_back",
                                  front_opening="plunge"),
        confidence=0.8,
        notes="Halter top; the straps tie behind the neck and the shoulders are bare.",
    )
    out = _refine_strap_style(feats)
    assert out.construction.strap_style == "halter_neck"


def test_thin_strap_top_without_neck_evidence_is_tank():
    """The recurring miscue: the model calls a thin-strap top a halter with no neck-support
    evidence in the notes. With no evidence it must be treated as a tank (spaghetti_straps),
    never full-backed, and generate as a band front + matching band back + over-shoulder
    straps, no sleeve."""
    from app.vision.analyzer import _refine_front_split, _refine_strap_style, _clamp_spaghetti_back

    feats = GarmentFeatures(
        garment_type=GarmentType.SHIRT, silhouette="fitted", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=None, details=[], sleeve_length="sleeveless", neckline="v_neck",
        construction=Construction(strap_style="halter_tie", back_coverage="low_back",
                                  front_opening="closed"),
        confidence=0.9,
        notes="Sleeveless, held up by thin straps, suggesting a halter style; v-neck.",
    )
    feats = _clamp_spaghetti_back(_refine_strap_style(_refine_front_split(feats)))
    assert feats.construction.strap_style == "spaghetti_straps"   # no neck evidence → tank
    assert feats.construction.back_coverage in ("low_back", "backless")   # never full

    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)
    assert "Sleeve" not in names
    assert any("Strap" in n for n in names), names           # over-shoulder straps
    front, back = _piece(psnap, "Front"), _piece(psnap, "Back Bodice")
    assert front is not None and back is not None and back["onFold"] is True

    def _top_y(piece):  # minimum y of the piece's outline = its top edge
        ids = set(piece["elementIds"])
        return min(min(e["start"]["y"], e["end"]["y"]) for e in psnap["elements"]
                   if e["id"] in ids and e["type"] in ("line", "curve"))
    # Tank back rises to the same level as the front (NOT a low underarm bandeau).
    assert abs(_top_y(front) - _top_y(back)) < 0.5


# ── Back coverage variants ─────────────────────────────────────────────────────

@pytest.mark.parametrize("coverage", ["full", "low_back", "racer"])
def test_back_coverage_keeps_back_panel(coverage: str):
    feats = _shirt_features(
        construction=Construction(strap_style="shoulder_seam", back_coverage=coverage),
    )
    names = _names(generate_pattern(feats, _measurements()))
    assert "Back Bodice" in names


def test_backless_omits_back_panel():
    feats = _shirt_features(construction=Construction(back_coverage="backless"))
    names = _names(generate_pattern(feats, _measurements()))
    assert "Back Bodice" not in names


# ── Regression: default construction == today's regular shirt ──────────────────

def test_default_construction_is_regular_shirt():
    feats = _shirt_features(construction=None, neckline="crew")
    names = _names(generate_pattern(feats, _measurements()))
    assert "Back Bodice" in names
    assert "Front Bodice" in names
    assert "Front" not in names          # halter-only continuous piece
    assert "Front Facing" not in names
    assert "Waist Tie" not in names


# ── Halter plunge stays ONE continuous front (no centre-front seam) ────────────

def test_halter_plunge_is_single_front_piece():
    feats = _shirt_features(
        construction=Construction(
            strap_style="halter_neck", back_coverage="low_back", front_opening="plunge",
        ),
        details=["v_neck", "tie_front", "spaghetti_straps"],
        neckline="halter",
    )
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)

    front = _piece(psnap, "Front")
    assert front is not None, names
    assert front["onFold"] is True          # ONE piece on the CF fold — no centre seam

    # Half back present (covered lower back), so no waist tie is needed.
    assert "Back Bodice" in names
    assert "Waist Tie" not in names

    # The v_neck detail must NOT leak into a junk "V_Neck" piece.
    assert not any("Neck" in n for n in names), names
    # No stray strap pieces either.
    assert not any("Strap" in n for n in names), names


def test_halter_plunge_backless_single_front_no_back():
    feats = _shirt_features(
        construction=Construction(
            strap_style="halter_neck", back_coverage="backless", front_opening="plunge",
        ),
        neckline="halter",
    )
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)

    front = _piece(psnap, "Front")
    assert front["onFold"] is True          # still one piece even when backless
    assert "Back Bodice" not in names
    assert "Waist Tie" in names


def test_halter_half_back_is_shoulderless():
    """The half-back band has a straight top edge (two top vertices at the same y)
    and no shoulder vertex."""
    feats = _shirt_features(
        construction=Construction(strap_style="halter_neck", back_coverage="low_back"),
        neckline="halter",
    )
    psnap = generate_pattern(feats, _measurements())
    back = _piece(psnap, "Back Bodice")
    assert back is not None

    ids = set(back["elementIds"])
    edges = [e for e in psnap["elements"] if e["id"] in ids and e["type"] in ("line", "curve")]
    top_ys = sorted({round(e["start"]["y"], 2) for e in edges})
    # The top (smallest y) edge is horizontal: its two endpoints share that y.
    top_edge = min(edges, key=lambda e: min(e["start"]["y"], e["end"]["y"]))
    assert round(top_edge["start"]["y"], 2) == round(top_edge["end"]["y"], 2), "top edge not flat"
    # No bezier (armhole-to-shoulder) curve — a shoulderless band is all straight lines.
    assert all(e["type"] == "line" for e in edges), "shoulderless back should have no curve"


# ── Analyzer: unseen halter back defaults to a covered half-back, not backless ──

def test_infer_unseen_halter_back_is_low_back():
    from app.vision.analyzer import _infer_construction_from_notes

    feats = GarmentFeatures(
        garment_type=GarmentType.BLOUSE,
        silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_back"),
        darts=DartFeature(front=0, back=0),
        details=["v_neck", "tie_front", "spaghetti_straps"],
        sleeve_length="sleeveless", neckline="v_neck",
        construction=None,
        confidence=0.8,
        notes="Halter-neck top, front rises into a strap that ties behind the neck. Deep V "
              "neckline plunges toward the midriff. The back is not visible.",
    )
    out = _infer_construction_from_notes(feats)
    assert out.construction is not None
    assert out.construction.strap_style == "halter_neck"
    assert out.construction.front_opening == "plunge"      # single front, not split
    assert out.construction.back_coverage == "low_back"    # covered half back, not backless


# ── End-to-end: representative recorded analyses (inline, not file-dependent) ──

def test_green_blouse_halter_backless_plunge_clean():
    """A halter / backless / plunge analysis yields a clean one-piece halter front with no
    back panel and no stray strap/neckline pieces."""
    feats = GarmentFeatures(
        garment_type=GarmentType.BLOUSE, silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0), details=["v_neck", "tie_front"],
        sleeve_length="sleeveless", neckline="halter",
        construction=Construction(strap_style="halter_neck", back_coverage="backless",
                                  front_opening="plunge"),
        confidence=0.82,
        notes="Halter blouse; the strap rises from the front and ties behind the neck; "
              "deep plunging V; the back is open/bare.",
    )
    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)

    front = _piece(psnap, "Front")
    assert front is not None and front["onFold"] is True   # one continuous front
    assert "Back Bodice" not in names                      # backless
    assert not any("Strap" in n or "Neck" in n for n in names), names


def test_halter_inferred_from_notes_is_half_back():
    """An analysis whose notes describe a halter (but omit the structured construction) is
    inferred as a one-piece halter front with a covered HALF back (not backless)."""
    from app.vision.analyzer import _infer_construction_from_notes

    feats = GarmentFeatures(
        garment_type=GarmentType.BLOUSE, silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_back"),
        darts=DartFeature(front=0, back=0), details=["tie_front", "spaghetti_straps"],
        sleeve_length="sleeveless", neckline="v_neck", construction=None, confidence=0.82,
        notes="Cropped halter top; the front rises into a strap that ties behind the neck "
              "(no shoulder seams). Deep V plunges toward the midriff. The back is not visible.",
    )
    feats = _infer_construction_from_notes(feats)

    assert feats.construction.strap_style == "halter_neck"
    assert feats.construction.front_opening == "plunge"
    assert feats.construction.back_coverage == "low_back"

    psnap = generate_pattern(feats, _measurements())
    names = _names(psnap)
    front = _piece(psnap, "Front")
    assert front is not None and front["onFold"] is True   # one piece, no CF seam
    assert "Back Bodice" in names                          # covered half back
    assert "Waist Tie" not in names
    assert not any("Strap" in n or "Neck" in n for n in names), names


# ── front_opening refinement: open/separate panels ⇒ deep_v_split, not plunge ──

def _blouse_with(notes: str, front_opening: str = "plunge") -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.BLOUSE, silhouette="fitted", length_category="cropped",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0), details=["v_neck", "tie_front"],
        sleeve_length="sleeveless", neckline="halter",
        construction=Construction(strap_style="halter_neck", back_coverage="low_back",
                                  front_opening=front_opening),
        confidence=0.8, notes=notes,
    )


def test_refine_upgrades_open_panels_to_split():
    from app.vision.analyzer import _refine_front_split

    feats = _blouse_with(
        "Halter top with a deep V plunge; the front panels appear to be open/loose at the "
        "centre on a single continuous front piece."
    )
    out = _refine_front_split(feats)
    assert out.construction.front_opening == "deep_v_split"


def test_refine_leaves_true_continuous_plunge():
    from app.vision.analyzer import _refine_front_split

    feats = _blouse_with(
        "Halter top with a deep plunging V neckline cut into one continuous front panel; "
        "the fabric is unbroken below the V."
    )
    out = _refine_front_split(feats)
    assert out.construction.front_opening == "plunge"


def test_open_panel_notes_upgrade_to_split_end_to_end():
    """A halter that reports plunge but whose notes describe open/loose front panels is
    upgraded to deep_v_split, and generates the split front (open V, top back-neck fold)."""
    from app.vision.analyzer import _refine_front_split

    feats = _refine_front_split(_blouse_with(
        "Olive halter top; the two front panels are separate and hang open at the centre, "
        "meeting only at the strap; gathered hem."
    ))
    assert feats.construction.front_opening == "deep_v_split"

    psnap = generate_pattern(feats, _measurements())
    front = _piece(psnap, "Front")
    ids = set(front["elementIds"])
    edges = [e for e in psnap["elements"] if e["id"] in ids and e["type"] in ("line", "curve")]

    # Split halter: the hem edge stops short of the centre (an open V at the centre),
    # unlike a plunge whose hem reaches the CF.
    hem = next(e for e in edges if e.get("seamLabel") == "hem")
    cf_x = min(e["start"]["x"] for e in edges)
    assert min(hem["start"]["x"], hem["end"]["x"]) > cf_x + 1.0, "hem should not reach the centre"

    # The fold must be the TOP (back-neck) seam — a horizontal edge at the minimum y —
    # so the two panels join only via the strap looping over the neck (not a centre seam).
    fold = next(e for e in edges if e.get("isFold"))
    assert abs(fold["start"]["y"] - fold["end"]["y"]) < 0.01, "fold should be horizontal (back-neck)"
    top_y = min(min(e["start"]["y"], e["end"]["y"]) for e in edges)
    assert abs(fold["start"]["y"] - top_y) < 0.01, "fold should sit at the very top (back-neck)"
