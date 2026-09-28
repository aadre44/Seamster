"""Trouser block tests: back seat tilt (#1) and front fly extension (#2)."""
import math

from app.models.features import (
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    WaistbandFeature,
)
from app.models.measurements import Measurements
from app.patterns.engine import _CARGO_POCKET_TOKENS, generate_pattern
from app.patterns.geometry import CurveSegment, Point
from app.patterns.llm_fallback import _TROUSER_DETAILS
from app.patterns.trousers import _FIT_PARAMS, build_trousers_block


def _measurements(**overrides) -> Measurements:
    defaults = dict(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0,
        chest_cm=90.0, shoulder_width_cm=30.0, arm_length_cm=60.0,
        inseam_cm=76.0, seam_allowance_cm=1.5,
    )
    defaults.update(overrides)
    return Measurements(**defaults)


def _features(**overrides) -> GarmentFeatures:
    defaults = dict(
        garment_type=GarmentType.TROUSERS, silhouette="regular",
        length_category="full_length",
        closure=ClosureFeature(type="center_front_zip", position="center_front"),
        darts=DartFeature(front=1, back=2),
        waistband=WaistbandFeature(type="straight", width_cm_estimate=4.0),
        details=[], confidence=0.9,
    )
    defaults.update(overrides)
    return GarmentFeatures(**defaults)


def _piece_elements(psnap, name):
    piece = next(pc for pc in psnap["pieces"] if pc["name"] == name)
    ids = set(piece["elementIds"])
    return piece, [e for e in psnap["elements"] if e["id"] in ids]


# ── #1 Back seat tilt ────────────────────────────────────────────────────────

def test_back_cb_seam_is_tilted_and_raised():
    """The CB waist corner leans toward the side and rises above the side waist."""
    block = build_trousers_block(_measurements(), fit_style="regular")
    back = block["back"]
    cb_waist = back.outline[0]      # [0] CB at waist
    cb_crotch = back.outline[9]     # [9] CB at crotch junction (CurveSegment)
    # leans: waist corner is further out (higher x) than the crotch junction
    assert cb_waist.x > cb_crotch.x
    # raised: waist corner sits above the (y=0) waistline
    assert cb_waist.y < 0.0


def test_back_cb_seam_longer_than_plain_vertical_rise():
    """Tilting + lifting makes the CB seam longer than a plain vertical rise."""
    m = _measurements()
    block = build_trousers_block(m, fit_style="regular")
    back = block["back"]
    cb_waist, cb_crotch = back.outline[0], back.outline[9]
    seam_len = math.hypot(cb_waist.x - cb_crotch.x, cb_waist.y - cb_crotch.y)
    vertical_rise = cb_crotch.y - 0.0   # what the old vertical seam measured
    assert seam_len > vertical_rise


def test_back_waist_quarter_preserved_along_slant():
    """Sewn back waist (slanted edge minus darts) stays ~waist_qt_b (W/4 - 0.5)."""
    m = _measurements()
    block = build_trousers_block(m, fit_style="regular")
    back = block["back"]
    cb_waist, ss_waist = back.outline[0], back.outline[1]
    span = math.hypot(ss_waist.x - cb_waist.x, ss_waist.y - cb_waist.y)
    sewn = span - sum(d.width for d in back.darts)
    assert abs(sewn - (m.waist_cm / 4 - 0.5)) < 0.25


def test_front_sewn_waist_is_the_front_quarter():
    """Front waist edge minus its dart = W/4 + 0.5 (darts not double-counted)."""
    m = _measurements()
    front = build_trousers_block(m, fit_style="regular")["front"]
    edge = front.outline[1].x - front.outline[0].x
    sewn = edge - sum(d.width for d in front.darts)
    assert math.isclose(sewn, m.waist_cm / 4 + 0.5, abs_tol=1e-6)
    assert front.darts  # still darted: the reduction is shared with the side seam


def test_front_leg_unchanged_by_tilt():
    """Seat tilt is back-only — the front waistline is still flat at y=0."""
    block = build_trousers_block(_measurements(), fit_style="regular", closure_type="elastic_waist")
    front = block["front"]
    assert front.outline[0].y == 0.0
    assert front.outline[1].y == 0.0


def test_back_darts_ride_the_slanted_waist():
    """Back dart legs sit on the tilted waist edge, not on y=0."""
    psnap = generate_pattern(_features(), _measurements())
    _, elems = _piece_elements(psnap, "Back Leg")
    # the raised CB corner means at least one outline vertex has y < the offset (2.0)
    ys = [e["start"]["y"] for e in elems]
    assert min(ys) < 2.0 - 0.5   # CB corner lifted above the layout origin


# ── #2 Fly: straight CF + applied J-shaped facing + shield ───────────────────

def test_zip_fly_keeps_straight_cf_and_emits_facing_and_shield():
    block = build_trousers_block(_measurements(), fit_style="regular", closure_type="zip_fly")
    front = block["front"]
    # CF is cut straight — no cut-on extension vertices
    assert len(front.outline) == 10
    # the waist has no vertex to the LEFT of the CF-at-waist corner
    cf_x = front.outline[0].x
    assert min(p.x for p in front.outline if p.y == 0.0) == cf_x
    # a separate J-shaped facing + a shield are emitted
    assert "fly_facing" in block and "fly_shield" in block


def test_fly_facing_is_j_shaped():
    """The applied facing has a curved (J) edge, not a plain rectangle."""
    facing = build_trousers_block(_measurements(), closure_type="zip_fly")["fly_facing"]
    assert any(isinstance(p, CurveSegment) for p in facing.outline)


def test_button_fly_facing_wider_than_zip():
    m = _measurements()
    zip_f = build_trousers_block(m, closure_type="zip_fly")["fly_facing"]
    btn_f = build_trousers_block(m, closure_type="button_fly")["fly_facing"]
    zip_w = max(p.x for p in zip_f.outline) - min(p.x for p in zip_f.outline)
    btn_w = max(p.x for p in btn_f.outline) - min(p.x for p in btn_f.outline)
    assert btn_w > zip_w


def test_fly_facing_width_tracks_fly_ext():
    facing = build_trousers_block(_measurements(), closure_type="zip_fly")["fly_facing"]
    width = max(p.x for p in facing.outline) - min(p.x for p in facing.outline)
    # fly_ext (3.5) + 3.0 allowance
    assert abs(width - 6.5) < 1e-6


def test_elastic_waist_has_no_fly_pieces_or_marks():
    block = build_trousers_block(_measurements(), closure_type="elastic_waist")
    front = block["front"]
    assert len(front.outline) == 10        # straight CF, no extension
    assert front.marks == []               # no fly marks
    assert "fly_facing" not in block and "fly_shield" not in block


def test_fly_topstitch_mark_is_interior_not_a_seam():
    """The fly topstitch is emitted but never becomes an outline edge/connection."""
    psnap = generate_pattern(
        _features(closure=ClosureFeature(type="center_front_zip", position="center_front")),
        _measurements(),
    )
    fly_ts = [e for e in psnap["elements"] if e.get("seamLabel") == "fly_topstitch"]
    assert fly_ts
    # the straight-CF model no longer marks a fold line
    assert [e for e in psnap["elements"] if e.get("seamLabel") == "fly_fold"] == []
    all_outline_ids = {eid for pc in psnap["pieces"] for eid in pc["elementIds"]}
    assert {e["id"] for e in fly_ts}.isdisjoint(all_outline_ids)
    conn_labels = {c["label"] for c in psnap["connections"]}
    assert "fly_topstitch" not in conn_labels


# ── Leg silhouette: no knee bulge + ankle scaling (#6) ───────────────────────

def _ss_levels(front):
    """Front side-seam x at thigh / knee / ankle (outline indices 3 / 4 / 5)."""
    return front.outline[3].x, front.outline[4].x, front.outline[5].x


def test_no_knee_bulge_for_any_fit():
    """The knee must never poke out beyond BOTH neighbours (the old jodhpur bulge)."""
    m = _measurements()
    for fit in _FIT_PARAMS:
        front = build_trousers_block(m, fit_style=fit)["front"]
        thigh, knee, ankle = _ss_levels(front)
        assert knee <= max(thigh, ankle) + 1e-6, f"{fit}: knee {knee} bulges past thigh {thigh} & ankle {ankle}"


def test_wide_and_palazzo_are_columnar():
    """Wide/palazzo: smooth side seam, knee between thigh and ankle (no balloon)."""
    m = _measurements()
    for fit in ("wide_leg", "palazzo"):
        thigh, knee, ankle = _ss_levels(build_trousers_block(m, fit_style=fit)["front"])
        lo, hi = sorted((thigh, ankle))
        assert lo - 1e-6 <= knee <= hi + 1e-6


def test_flared_and_bootcut_flare_to_the_hem():
    """Flared/bootcut: hem wider than the knee, and the knee nips in below the thigh."""
    m = _measurements()
    for fit in ("flared", "bootcut"):
        thigh, knee, ankle = _ss_levels(build_trousers_block(m, fit_style=fit)["front"])
        assert ankle > knee, f"{fit}: ankle {ankle} should flare past knee {knee}"
        assert knee < thigh, f"{fit}: knee {knee} should nip in below thigh {thigh}"


def test_ankle_scales_with_body_size():
    """A larger hip yields a larger ankle opening for the same fit."""
    small = build_trousers_block(_measurements(hip_cm=80.0, waist_cm=64.0), fit_style="wide_leg")["front"]
    large = build_trousers_block(_measurements(hip_cm=120.0, waist_cm=104.0), fit_style="wide_leg")["front"]
    small_ankle = small.outline[5].x - small.outline[6].x
    large_ankle = large.outline[5].x - large.outline[6].x
    assert large_ankle > small_ankle + 2.0


def test_ankle_floor_keeps_small_skinny_sewable():
    """A very small skinny ankle is floored so the foot still passes."""
    front = build_trousers_block(_measurements(hip_cm=70.0, waist_cm=56.0), fit_style="skinny")["front"]
    ankle_half = (front.outline[5].x - front.outline[6].x) / 2
    assert ankle_half >= 6.5 - 1e-6


# ── Cargo pocket de-duplication ──────────────────────────────────────────────

def test_cargo_synonyms_build_native_pocket():
    """Each cargo synonym is recognised by the native builder (one Cargo Pocket pair)."""
    for token in ("cargo_pockets", "bellows_pocket", "flap_pockets", "utility_pocket", "patch_pocket_flap"):
        psnap = generate_pattern(_features(details=[token]), _measurements())
        names = [pc["name"] for pc in psnap["pieces"]]
        assert "Cargo Pocket" in names, f"{token} did not build a native Cargo Pocket"
        assert names.count("Cargo Pocket Flap") == 1, f"{token} produced duplicate flaps"
        assert "Cargo Pocket Bag" not in names, f"{token} produced a stray Cargo Pocket Bag"


def test_cargo_synonyms_registered_to_skip_llm_fallback():
    """Every native cargo synonym is also registered so the LLM fallback never duplicates it."""
    for token in _CARGO_POCKET_TOKENS:
        assert token in _TROUSER_DETAILS, f"{token} missing from _TROUSER_DETAILS"


# ── Cargo bellows pocket (#4) ────────────────────────────────────────────────

def test_cargo_bellows_bag_has_depth_and_fold_marks():
    """Default cargo bag is a 3-D bellows: wider than the flap and carrying fold marks."""
    block = build_trousers_block(_measurements(), has_cargo_pocket=True)  # default bellows
    bag = block["cargo_pocket"]
    flap = block["cargo_pocket_flap"]
    bag_w = max(p.x for p in bag.outline) - min(p.x for p in bag.outline)
    flap_w = max(p.x for p in flap.outline) - min(p.x for p in flap.outline)
    assert bag_w > flap_w  # bag carries the side bellows allowance, the flap does not
    labels = {mk.label for mk in bag.marks}
    assert "bellows_fold" in labels and "pocket_facing_fold" in labels


def test_cargo_flat_style_is_square_with_no_bellows():
    block = build_trousers_block(_measurements(), has_cargo_pocket=True, cargo_style="flat")
    bag = block["cargo_pocket"]
    assert bag.marks == []          # no bellows folds
    assert len(bag.outline) == 4    # plain square patch


def test_cargo_gusset_style_emits_gusset_strip():
    block = build_trousers_block(_measurements(), has_cargo_pocket=True, cargo_style="gusset")
    assert "cargo_pocket_gusset" in block


def test_cargo_flap_takes_shape_from_detail_token():
    """pocket_pointed -> a pointed (5-vertex) cargo flap, not a square."""
    psnap = generate_pattern(_features(details=["cargo_pocket", "pocket_pointed"]), _measurements())
    _, verts = _piece_elements(psnap, "Cargo Pocket Flap")
    assert len(verts) == 5


def test_cargo_flat_token_selects_flat_style():
    psnap = generate_pattern(_features(details=["cargo_flat"]), _measurements())
    names = [pc["name"] for pc in psnap["pieces"]]
    assert "Cargo Pocket" in names and "Cargo Pocket Bag" not in names
    _, cargo = _piece_elements(psnap, "Cargo Pocket")
    assert len(cargo) == 4   # flat square bag


def test_cargo_pocket_places_marks_on_front_leg():
    psnap = generate_pattern(_features(details=["cargo_pocket"]), _measurements())
    placement = [e for e in psnap["elements"] if e.get("seamLabel") == "cargo_pocket_placement"]
    bartack = [e for e in psnap["elements"] if e.get("seamLabel") == "bartack"]
    assert placement and len(bartack) == 2
    # the leg marks are interior — never part of a sewn outline or a seam connection
    all_outline_ids = {eid for pc in psnap["pieces"] for eid in pc["elementIds"]}
    assert {e["id"] for e in placement + bartack}.isdisjoint(all_outline_ids)
