"""Jacket base block (Aldrich-inspired parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Origin: x=0 is CB/CF fold/seam edge; y=0 is shoulder/nape level
  - y increases toward hem
  - Front bodice is always cut off-fold (CF is the opening edge)

Pieces always produced:
  Back Bodice, Front Bodice, Sleeve

Conditional pieces:
  Back Yoke       — has_yoke=True  (splits back into yoke + lower panel, e.g. denim, western)
  Collar          — has_collar=True  (height & width driven by collar_type)
  Front Facing    — has_facing=True (lapel/CF facing strip; width driven by breast_style)
  Patch Pocket    — has_patch_pockets=True
  Welt Strip +
    Pocket Bag    — has_welt_pockets=True
  Cuff Band       — has_cuff_band=True  (rib knit cuff, bomber/varsity)
  Hem Band        — has_hem_band=True   (rib knit hem band, bomber/varsity)
  Hood Panel      — has_hood=True
  Back Lining +
    Front Lining  — has_lining=True
  Belt Strap      — has_belt=True   (on-fold half-belt, trench/military)
  Epaulet Tab     — has_epaulets=True (shoulder tab, military)

Fit styles (silhouette):
  fitted, slim, regular, relaxed, boxy, oversized,
  moto, bomber, military, denim, anorak, varsity

Collar types (sub-type axis):
  notch_lapel, peak_lapel, shawl_collar, band_collar, no_collar

Breast styles (sub-type axis):
  single_breasted, double_breasted

Sleeve lengths:
  long, three_quarter, short, puff, puff_short

Length categories:
  waist_length, cropped, hip_length, below_hip, knee
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.pockets import make_patch_pocket, make_welt_pocket
from app.patterns.skirts import PieceSpec

EASE_CHEST = 8.0      # standard jacket chest ease (2 cm more than a shirt)
_FACING_W  = 6.5      # cm width of front facing / lapel strip
_COLLAR_H  = 4.5      # cm collar height (piece folds at centre for two layers)
_CUFF_H    = 7.0      # cm rib cuff band height (bomber / varsity)
_HEM_BAND_H = 5.5     # cm rib hem band height (bomber / varsity)
_BUTTON_CUFF_H   = 6.0   # cm height of woven button/snap cuff (not rib knit)
_SLEEVE_PLACKET_W = 3.5  # cm width of sleeve vent/placket strip
_BREAST_POCKET_W  = 12.0 # cm width of breast/chest welt pocket opening

# ── Fit-style parameter table ──────────────────────────────────────────────────
# shoulder_slope : cm drop from neckline level to shoulder tip (y downward)
# armhole_extra  : cm added to base arm_depth (chest/4 + 4) for looser armhole
# waist_suppress : how much narrower the side seam is at waist vs chest quarter
# drop_shoulder  : cm the shoulder tip extends beyond shoulder_qt outward
# hem_ease       : cm added to chest_qt at the hem for a slight flare or box shape
_FIT_PARAMS: dict[str, dict] = {
    # ── Structured / tailored ─────────────────────────────────────────────────
    "fitted":    dict(shoulder_slope=0.5,  armhole_extra=-0.5, waist_suppress=3.0, drop_shoulder=0.0, hem_ease=0.0),
    "slim":      dict(shoulder_slope=0.5,  armhole_extra=-1.0, waist_suppress=2.5, drop_shoulder=0.0, hem_ease=0.0),
    "regular":   dict(shoulder_slope=1.5,  armhole_extra= 0.0, waist_suppress=1.5, drop_shoulder=0.0, hem_ease=1.0),
    "relaxed":   dict(shoulder_slope=2.0,  armhole_extra= 1.0, waist_suppress=0.0, drop_shoulder=0.5, hem_ease=2.0),
    "boxy":      dict(shoulder_slope=2.5,  armhole_extra= 2.0, waist_suppress=0.0, drop_shoulder=2.0, hem_ease=2.0),
    "oversized": dict(shoulder_slope=3.5,  armhole_extra= 3.0, waist_suppress=0.0, drop_shoulder=4.0, hem_ease=4.0),
    # ── Specialty silhouettes ─────────────────────────────────────────────────
    "moto":      dict(shoulder_slope=0.5,  armhole_extra=-0.5, waist_suppress=2.5, drop_shoulder=0.0, hem_ease=0.0),
    "bomber":    dict(shoulder_slope=2.5,  armhole_extra= 1.5, waist_suppress=0.0, drop_shoulder=2.0, hem_ease=0.0),
    "military":  dict(shoulder_slope=0.5,  armhole_extra=-0.5, waist_suppress=3.0, drop_shoulder=0.0, hem_ease=0.0),
    # denim: squared shoulder, slight yoke ease, straighter sides than "boxy"
    "denim":     dict(shoulder_slope=2.0,  armhole_extra= 0.5, waist_suppress=0.0, drop_shoulder=1.0, hem_ease=1.5),
    # anorak: pullover-style, deep armhole, roomy body, draw-cord hem
    "anorak":    dict(shoulder_slope=2.5,  armhole_extra= 2.5, waist_suppress=0.0, drop_shoulder=1.5, hem_ease=3.0),
    # varsity: bomber proportions with set-in sleeve (no rib hem — uses woven hem band)
    "varsity":   dict(shoulder_slope=2.5,  armhole_extra= 1.5, waist_suppress=0.0, drop_shoulder=2.5, hem_ease=0.0),
}
_DEFAULT_FIT = _FIT_PARAMS["regular"]

# ── Fixed body lengths from shoulder/nape (y=0) — None → use m.length_cm ─────
_LENGTH_CM: dict[str, float | None] = {
    "waist_length": 40.0,   # very short crop; hem sits at natural waist
    "cropped":      45.0,
    "hip_length":   60.0,
    "below_hip":    72.0,
    "knee":         None,
}

# ── Sleeve type → (length_factor, cap_width_factor) ──────────────────────────
# length_factor  : multiplier of arm_length (or fixed cm when negative)
# cap_w_factor   : multiplier of base cap_w_half (> 1 = wider/puffier cap)
_SLEEVE_PARAMS: dict[str, dict] = {
    "long":          dict(fixed_len=None,  length_factor=1.00, cap_w_factor=1.00),
    "three_quarter": dict(fixed_len=None,  length_factor=0.67, cap_w_factor=1.00),
    "short":         dict(fixed_len=25.0,  length_factor=None, cap_w_factor=1.00),
    "puff":          dict(fixed_len=None,  length_factor=1.00, cap_w_factor=1.40),
    "puff_short":    dict(fixed_len=18.0,  length_factor=None, cap_w_factor=1.40),
}

# ── Collar-type parameter table ────────────────────────────────────────────────
# collar_h_factor : multiplied by _COLLAR_H to get the folded collar height
# collar_w_extra  : cm added to neck_circ for the collar piece width
# skip            : if True the collar piece is not generated even with has_collar=True
_COLLAR_TYPE_PARAMS: dict[str, dict] = {
    "notch_lapel":  dict(collar_h_factor=1.00, collar_w_extra=0.0,  skip=False),
    "peak_lapel":   dict(collar_h_factor=1.35, collar_w_extra=2.0,  skip=False),
    "shawl_collar": dict(collar_h_factor=1.20, collar_w_extra=5.0,  skip=False),
    "band_collar":  dict(collar_h_factor=0.55, collar_w_extra=0.0,  skip=False),
    "no_collar":    dict(collar_h_factor=0.0,  collar_w_extra=0.0,  skip=True),
}
_DEFAULT_COLLAR_TYPE = _COLLAR_TYPE_PARAMS["notch_lapel"]

# ── Breast-style parameter table ───────────────────────────────────────────────
# facing_w_factor : multiplied by _FACING_W to get the CF facing strip width
# cf_overlap_extra: additional cm added to front bodice width at CF (double-breasted underlap)
_BREAST_PARAMS: dict[str, dict] = {
    "single_breasted": dict(facing_w_factor=1.0,  cf_overlap_extra=0.0),
    "double_breasted":  dict(facing_w_factor=2.4,  cf_overlap_extra=6.0),
}
_DEFAULT_BREAST = _BREAST_PARAMS["single_breasted"]


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _rect_piece(
    name: str, w: float, h: float, cut_qty: int, sa: float, on_fold: bool = False, notes: str = ""
) -> PieceSpec:
    """Rectangular PieceSpec with a horizontal centre grain line."""
    return PieceSpec(
        name=name,
        outline=[Point(0.0, 0.0), Point(w, 0.0), Point(w, h), Point(0.0, h)],
        darts=[],
        grain_start=Point(w * 0.2, h / 2),
        grain_end=Point(w * 0.8, h / 2),
        cut_qty=cut_qty,
        on_fold=on_fold,
        seam_allowance=sa,
        notes=notes,
    )


def build_jacket_block(
    m: Measurements,
    fit_style: str = "regular",
    sleeve_length: str = "long",
    length_category: str = "hip_length",
    closure_type: str = "button_front",   # button_front | zip | snap | none
    collar_type: str = "notch_lapel",     # notch_lapel | peak_lapel | shawl_collar | band_collar | no_collar
    breast_style: str = "single_breasted",  # single_breasted | double_breasted
    has_yoke: bool = False,
    has_collar: bool = True,
    has_facing: bool = True,
    has_patch_pockets: bool = False,
    has_welt_pockets: bool = False,
    has_cuff_band: bool = False,
    has_hem_band: bool = False,
    has_hood: bool = False,
    has_lining: bool = False,
    has_two_piece_sleeve: bool = False,  # upper + under sleeve (tailored construction)
    has_cuff: bool = False,              # woven button/snap cuff (distinct from rib has_cuff_band)
    has_breast_pocket: bool = False,     # small chest/breast welt pocket
    has_in_seam_pockets: bool = False,   # slash/side-seam pocket bags
    has_sleeve_placket: bool = False,    # vent strip at cuff opening
    has_belt: bool = False,              # on-fold half-belt (trench / military)
    has_epaulets: bool = False,          # shoulder tab (military / utility)
    pocket_shape: str = "square",        # square | rounded | angled | pointed | curved
) -> dict[str, PieceSpec]:
    """Return jacket pattern pieces shaped by the analysed garment features.

    Fit styles    : fitted, slim, regular, relaxed, boxy, oversized,
                    moto, bomber, military, denim, anorak, varsity
    Collar types  : notch_lapel, peak_lapel, shawl_collar, band_collar, no_collar
    Breast styles : single_breasted, double_breasted
    Sleeve lengths: long, three_quarter, short, puff, puff_short
    Length cats   : waist_length, cropped, hip_length, below_hip, knee
    Closure       : button_front, zip, snap, none
    Two-piece sleeve: upper_sleeve + under_sleeve (fitted/slim/moto/military construction)
    Optional extras : cuff, breast_pocket/welt, in_seam pocket_bag, sleeve_placket,
                      belt_strap, epaulet_tab
    """
    # ── Fit params ────────────────────────────────────────────────────────────
    fit_style = (fit_style or "regular").lower()
    fp = _FIT_PARAMS.get(fit_style, _DEFAULT_FIT)

    # ── Collar-type params ────────────────────────────────────────────────────
    collar_type = (collar_type or "notch_lapel").lower()
    ct = _COLLAR_TYPE_PARAMS.get(collar_type, _DEFAULT_COLLAR_TYPE)

    # ── Breast-style params ───────────────────────────────────────────────────
    breast_style = (breast_style or "single_breasted").lower()
    bp = _BREAST_PARAMS.get(breast_style, _DEFAULT_BREAST)
    cf_overlap_extra = bp["cf_overlap_extra"]
    shoulder_slope = fp["shoulder_slope"]
    armhole_extra  = fp["armhole_extra"]
    waist_suppress = fp["waist_suppress"]
    drop_shoulder  = fp["drop_shoulder"]
    hem_ease       = fp["hem_ease"]

    # ── Measurements ──────────────────────────────────────────────────────────
    chest      = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    shoulder   = m.shoulder_width_cm if m.shoulder_width_cm is not None else (chest / 4 + 7.5)
    arm_length = m.arm_length_cm if m.arm_length_cm is not None else 60.0
    sa         = m.seam_allowance_cm

    fixed_L = _LENGTH_CM.get(length_category)
    L = fixed_L if fixed_L is not None else m.length_cm
    L = max(L, 40.0)

    # ── Key quarter measurements ───────────────────────────────────────────────
    chest_qt       = (chest + EASE_CHEST) / 4
    shoulder_qt    = shoulder / 2
    back_neck_w    = chest / 10 + 1.0
    front_neck_w   = back_neck_w
    arm_depth      = chest / 4 + 4.0 + armhole_extra    # armhole level from shoulder
    waist_y        = arm_depth + 18.0                    # natural waist level
    shoulder_tip_x = shoulder_qt + drop_shoulder

    # Side-seam widths
    waist_side = max(chest_qt - waist_suppress, chest_qt * 0.72)
    hem_side   = chest_qt + hem_ease

    # Front neck opening: V-style, deeper than shirt for jacket proportion
    front_neck_depth = chest / 10 + 4.0

    # Yoke seam: just below the armhole (for denim / western split)
    yoke_seam_y = arm_depth + 3.0

    # Sleeve cap geometry
    cap_height   = chest / 8
    cap_w_half   = chest_qt - 1.0

    pieces: dict[str, PieceSpec] = {}

    # ── Back: yoke + panel OR single bodice ───────────────────────────────────
    if has_yoke:
        # Back Yoke — holds the neckline, shoulder seam, and upper armhole
        yoke_outline: list[Point] = [
            Point(0.0, 0.0),
            Point(back_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            Point(chest_qt, arm_depth),
            Point(chest_qt, yoke_seam_y),
            Point(0.0, yoke_seam_y),
        ]
        pieces["back_yoke"] = PieceSpec(
            name="Back Yoke",
            outline=yoke_outline,
            darts=[],
            grain_start=Point(chest_qt / 2, arm_depth * 0.5),
            grain_end=Point(chest_qt / 2, yoke_seam_y * 0.9),
            cut_qty=2,
            on_fold=True,
            seam_allowance=sa,
            notes="upper back yoke panel cut on fold; sew to Back Panel at yoke seam first, then join shoulder seams to Front Bodice",
            edge_labels={0: "neckline", 1: "shoulder", 2: "armhole", 3: "armhole", 4: "yoke_seam", 5: "center_back"},
        )

        # Back Panel — lower back from yoke seam to hem
        if waist_suppress > 0.0 and waist_y <= L:
            panel_outline: list[Point] = [
                Point(0.0, yoke_seam_y),
                Point(chest_qt, yoke_seam_y),
                Point(waist_side, waist_y),
                Point(hem_side, L),
                Point(0.0, L),
            ]
        else:
            panel_outline = [
                Point(0.0, yoke_seam_y),
                Point(chest_qt, yoke_seam_y),
                Point(hem_side, L),
                Point(0.0, L),
            ]
        _pn = len(panel_outline)
        pieces["back_panel"] = PieceSpec(
            name="Back Panel",
            outline=panel_outline,
            darts=[],
            grain_start=Point(chest_qt / 2, yoke_seam_y + (L - yoke_seam_y) * 0.2),
            grain_end=Point(chest_qt / 2, L * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=sa,
            notes="lower back body panel cut on fold; sew to Back Yoke at yoke seam, then side seams to Front Bodice",
            edge_labels={0: "yoke_seam", **{i: "side_seam" for i in range(1, _pn - 2)}, _pn - 2: "hem", _pn - 1: "center_back"},
        )

    else:
        # Back Bodice — single piece from neckline to hem
        if waist_suppress > 0.0 and waist_y <= L:
            back_outline: list[Point] = [
                Point(0.0, 0.0),
                Point(back_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                Point(chest_qt, arm_depth),
                Point(waist_side, waist_y),
                Point(hem_side, L),
                Point(0.0, L),
            ]
        else:
            back_outline = [
                Point(0.0, 0.0),
                Point(back_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                Point(chest_qt, arm_depth),
                Point(hem_side, L),
                Point(0.0, L),
            ]
        _bbn = len(back_outline)
        pieces["back_bodice"] = PieceSpec(
            name="Back Bodice",
            outline=back_outline,
            darts=[],
            grain_start=Point(chest_qt / 2, arm_depth),
            grain_end=Point(chest_qt / 2, L * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=sa,
            notes="single back body panel cut on fold; sew to Front Bodice at shoulder seams then side seams",
            edge_labels={0: "neckline", 1: "shoulder", 2: "armhole", **{i: "side_seam" for i in range(3, _bbn - 2)}, _bbn - 2: "hem", _bbn - 1: "center_back"},
        )

    # ── Front Bodice (always off-fold; CF is the opening/closure edge) ────────
    # V-style neckline suits most jacket types; the lapel shape is formed by the
    # front facing piece folded back over the CF — no extra lapel notch in the
    # main front piece keeps the block garment-type-neutral.
    # Double-breasted: the underlap zone is added to the side-seam side so all
    # x values remain positive (simpler layout); the wider facing piece encodes
    # the visible overlap when the jacket is worn.
    front_hem   = hem_side  + cf_overlap_extra
    front_chest = chest_qt  + cf_overlap_extra
    if waist_suppress > 0.0 and waist_y <= L:
        front_outline: list[Point] = [
            Point(0.0, front_neck_depth),
            Point(front_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            Point(front_chest, arm_depth),
            Point(waist_side + cf_overlap_extra, waist_y),
            Point(front_hem, L),
            Point(0.0, L),
        ]
    else:
        front_outline = [
            Point(0.0, front_neck_depth),
            Point(front_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            Point(front_chest, arm_depth),
            Point(front_hem, L),
            Point(0.0, L),
        ]
    _fn = len(front_outline)
    pieces["front_bodice"] = PieceSpec(
        name="Front Bodice",
        outline=front_outline,
        darts=[],
        grain_start=Point(front_chest / 2, arm_depth),
        grain_end=Point(front_chest / 2, L * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes="front body panel (left and right cut separately, mirror when cutting); interface CF edge; attach facing before joining shoulder and side seams to back",
        edge_labels={0: "neckline", 1: "shoulder", 2: "armhole", **{i: "side_seam" for i in range(3, _fn - 2)}, _fn - 2: "hem", _fn - 1: "center_front"},
    )

    # ── Sleeve ────────────────────────────────────────────────────────────────
    sleeve_length = (sleeve_length or "long").lower()

    if sleeve_length != "sleeveless":
        sp = _SLEEVE_PARAMS.get(sleeve_length, _SLEEVE_PARAMS["long"])
        cap_w = cap_w_half * sp["cap_w_factor"]

        if sp["fixed_len"] is not None:
            actual_len = sp["fixed_len"]
        else:
            actual_len = arm_length * sp["length_factor"]

        total_sleeve_h = cap_height + actual_len
        sleeve_wrist   = max(cap_w - 3.0, cap_w * 0.75)  # taper toward wrist

        if has_two_piece_sleeve:
            # Tailored two-piece sleeve: upper sleeve carries the sleeve crown;
            # under sleeve is narrower and flatter (fitted/moto/military construction).
            upper_w = cap_w * 0.65
            under_w = cap_w * 0.48
            wrist_u = max(upper_w - 2.0, upper_w * 0.74)
            wrist_d = max(under_w - 1.5, under_w * 0.70)
            pieces["upper_sleeve"] = PieceSpec(
                name="Upper Sleeve",
                outline=[
                    Point(0.0, 0.0),
                    Point(upper_w, cap_height),
                    Point(wrist_u, total_sleeve_h),
                    Point(0.0, total_sleeve_h),
                ],
                darts=[],
                grain_start=Point(upper_w / 2, cap_height * 0.5),
                grain_end=Point(upper_w / 2, total_sleeve_h * 0.85),
                cut_qty=2,
                on_fold=False,
                seam_allowance=sa,
                notes="upper section of two-piece tailored sleeve; carries the sleeve crown; sew to Under Sleeve at both sleeve seams first, then set the assembled sleeve into the armscye",
                edge_labels={0: "armhole", 1: "sleeve_seam", 2: "wrist", 3: "sleeve_seam"},
            )
            pieces["under_sleeve"] = PieceSpec(
                name="Under Sleeve",
                outline=[
                    Point(0.0, 0.0),
                    Point(under_w, cap_height * 0.55),
                    Point(wrist_d, total_sleeve_h),
                    Point(0.0, total_sleeve_h),
                ],
                darts=[],
                grain_start=Point(under_w / 2, cap_height * 0.3),
                grain_end=Point(under_w / 2, total_sleeve_h * 0.85),
                cut_qty=2,
                on_fold=False,
                seam_allowance=sa,
                notes="under section of two-piece tailored sleeve; flatter cut for inside arm; sew to Upper Sleeve, press seams, then insert assembled sleeve as a unit into the armscye",
                edge_labels={1: "sleeve_seam", 3: "sleeve_seam"},
            )
        else:
            pieces["sleeve"] = PieceSpec(
                name="Sleeve",
                outline=[
                    Point(0.0, 0.0),
                    Point(cap_w, cap_height),
                    Point(sleeve_wrist, total_sleeve_h),
                    Point(0.0, total_sleeve_h),
                ],
                darts=[],
                grain_start=Point(cap_w / 2, cap_height * 0.5),
                grain_end=Point(cap_w / 2, total_sleeve_h * 0.85),
                cut_qty=2,
                on_fold=True,
                seam_allowance=sa,
                notes="one-piece jacket sleeve; sew sleeve seam to form tube, ease cap into armscye; finish hem to cuff band or fold back for turn-up",
                edge_labels={0: "armhole", 1: "sleeve_seam", 2: "wrist", 3: "center_sleeve"},
            )

    # ── Collar ─────────────────────────────────────────────────────────────────
    # Rectangle sized to neck circumference; folds at centre for two layers.
    # Height and width are driven by collar_type via _COLLAR_TYPE_PARAMS.
    if has_collar and not ct["skip"]:
        neck_circ = (back_neck_w + front_neck_w) * 2 + sa * 2 + ct["collar_w_extra"]
        collar_h  = _COLLAR_H * ct["collar_h_factor"]
        pieces["collar"] = _rect_piece("Collar", neck_circ, collar_h * 2, 1, sa, on_fold=True,
            notes="jacket collar cut on fold to give two layers; interface; sew outer collar to neckline RS together, then fell-stitch inner collar over seam allowance")

    # ── Front Facing ───────────────────────────────────────────────────────────
    # Strip along the CF from neckline to hem: forms the lapel fold-back zone
    # and the button / zip underlap. Width driven by breast_style:
    # double-breasted needs a much wider strip to cover the underlap zone.
    # Cut × 2 (one each front panel).
    if has_facing:
        facing_h = L - front_neck_depth + sa * 2
        facing_w = _FACING_W * bp["facing_w_factor"]
        pieces["front_facing"] = _rect_piece("Front Facing", facing_w, facing_h, 2, sa,
            notes="front facing/lapel strip; interface; sew to CF of Front Bodice RS together, understitch, then turn and press to form lapel")

    # ── Patch Pockets ──────────────────────────────────────────────────────────
    if has_patch_pockets:
        pocket_w = max(12.0, chest_qt * 0.52)
        pocket_h = max(14.0, chest_qt * 0.62)
        pieces["patch_pocket"] = make_patch_pocket(
            "Patch Pocket", pocket_w, pocket_h, sa, shape=pocket_shape, cut_qty=2,
            notes="patch pocket; interface; press under seam allowances and topstitch to Front Bodice before assembling body")

    # ── Welt Pockets ───────────────────────────────────────────────────────────
    # Two pieces per pocket: a narrow welt strip and the inner pocket bag.
    if has_welt_pockets:
        welt_w = max(13.0, chest_qt * 0.58)
        pieces["welt_strip"], pieces["welt_pocket_bag"] = make_welt_pocket(
            welt_w, sa, name_prefix="Welt", welt_h=2.5 / 2, bag_depth=16.0, cut_qty=2,
            placement_note="on the Front Bodice",
        )

    # ── Cuff Band (bomber / varsity rib knit) ──────────────────────────────────
    # Cut 15 % shorter than wrist circumference — rib stretches when sewn.
    if has_cuff_band:
        wrist_circ = (cap_w_half - 2.0) * 2 * 0.85
        pieces["cuff_band"] = _rect_piece("Cuff Band", wrist_circ, _CUFF_H, 2, sa,
            notes="rib knit cuff band cut 15% shorter than wrist circumference; sew short ends to form tube; attach to sleeve hem RS together, stretching band to fit")

    # ── Hem Band (bomber / varsity rib knit) ───────────────────────────────────
    # Half of full chest circumference (cut on fold), 15 % shorter for stretch.
    if has_hem_band:
        hem_band_w = chest_qt * 4 * 0.85 / 2
        pieces["hem_band"] = _rect_piece("Hem Band", hem_band_w, _HEM_BAND_H, 1, sa, on_fold=True,
            notes="rib knit hem band cut on fold at 15% shorter than chest circumference; sew short ends to form tube; attach to jacket hem RS together, stretching to fit")

    # ── Hood Panel ─────────────────────────────────────────────────────────────
    # Simplified single-panel approximation.  Width ≈ half head circumference;
    # height ≈ nape-to-crown distance.
    if has_hood:
        hood_w = chest_qt * 1.12           # ~29–32 cm (half head circ)
        hood_h = arm_depth + 10.0          # ~35–38 cm (nape to crown)
        pieces["hood_panel"] = _rect_piece("Hood Panel", hood_w, hood_h, 2, sa,
            notes="two-piece hood panel; sew centre seam RS together first to form hood shape, then attach open edge to neckline")

    # ── Woven Cuff (button / snap — denim, military, tailored) ───────────────
    # Distinct from the rib knit cuff_band. Folds on the long edge for two layers.
    if has_cuff and sleeve_length not in ("sleeveless", "short"):
        wrist_circ = (cap_w_half - 2.0) * 2 + sa * 2
        pieces["cuff"] = _rect_piece("Cuff", wrist_circ, _BUTTON_CUFF_H * 2, 2, sa, on_fold=True,
            notes="woven button cuff cut on fold for two layers; interface; sew short ends, fold in half and attach to sleeve hem; buttons and buttonholes on overlap")

    # ── Breast / Chest Welt Pocket ────────────────────────────────────────────
    # Single small welt on left chest (blazer, military, denim jacket).
    if has_breast_pocket:
        pieces["breast_pocket_welt"] = _rect_piece("Breast Pocket Welt", _BREAST_POCKET_W, 2.5, 1, sa,
            notes="single welt for left breast pocket; interface; construct welt opening on Front Bodice before assembling")
        pieces["breast_pocket_bag"]  = _rect_piece("Breast Pocket Bag",  _BREAST_POCKET_W, 14.0, 1, sa,
            notes="breast pocket bag; slip inside welt opening and stitch bag to seam allowances only")

    # ── In-Seam / Slash Pocket Bags ──────────────────────────────────────────
    # Hidden bag sits inside the side seam; the opening is cut into the front panel.
    if has_in_seam_pockets:
        bag_w = max(14.0, chest_qt * 0.62)
        bag_h = max(16.0, chest_qt * 0.72)
        pieces["pocket_bag"] = _rect_piece("Pocket Bag", bag_w, bag_h, 2, sa,
            notes="in-seam/slash pocket bag; insert into side seam before closing body seams; bag hangs inside garment")

    # ── Sleeve Placket / Cuff Vent ────────────────────────────────────────────
    # Narrow strip at the sleeve hem that forms the vent opening for cuff buttons.
    if has_sleeve_placket and sleeve_length not in ("sleeveless", "short"):
        placket_h = max(10.0, arm_length * 0.18)
        pieces["sleeve_placket"] = _rect_piece("Sleeve Placket", _SLEEVE_PLACKET_W, placket_h, 2, sa,
            notes="sleeve placket/cuff vent strip; interface; slash sleeve hem and insert placket to form vent opening for cuff buttons")

    # ── Belt Strap ─────────────────────────────────────────────────────────────
    # On-fold half-belt sized to chest circumference; height 5 cm (doubled to 10 cm
    # when cut on fold). Used on trench, military, and utility jackets.
    if has_belt:
        belt_half_w = chest_qt * 4 * 0.5  # half of full chest circ (cut on fold)
        pieces["belt_strap"] = _rect_piece("Belt Strap", belt_half_w, 5.0 * 2, 1, sa, on_fold=True)

    # ── Epaulet Tab ────────────────────────────────────────────────────────────
    # Narrow rectangular tab sewn at the shoulder seam; fastens with a button.
    # Width ≈ shoulder_qt / 3; height 8 cm. Cut × 2 (one per shoulder).
    if has_epaulets:
        epaulet_w = max(4.0, shoulder_qt / 3)
        pieces["epaulet_tab"] = _rect_piece("Epaulet Tab", epaulet_w, 8.0, 2, sa)

    # ── Lining ─────────────────────────────────────────────────────────────────
    # Lining pieces mirror the outer silhouette; modelled as approximating
    # rectangles here (patternmaker traces them from the outer pieces).
    if has_lining:
        lining_w = hem_side
        pieces["back_lining"]  = _rect_piece("Back Lining",  lining_w, L, 2, sa, on_fold=True)
        pieces["front_lining"] = _rect_piece("Front Lining", lining_w, L, 2, sa)

    return pieces
