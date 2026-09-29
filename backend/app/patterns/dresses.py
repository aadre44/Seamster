"""Dress base block (Aldrich parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Bodice origin: x=0 is CF/CB fold edge, y=0 is shoulder/nape level
  - Skirt origin: x=0 is CF/CB fold edge, y=0 is waist (or empire seam)
  - Bodice and skirt pieces are each positioned independently on the canvas

Pieces always produced:
  Front Bodice, Back Bodice, Front Skirt, Back Skirt

Conditional pieces:
  Sleeve           — all sleeve_length except "sleeveless" and "spaghetti"
  Spaghetti Strap  — when sleeve_length == "spaghetti"
  Bodice Facing    — when neckline is "strapless" or "halter"
  Collar           — when has_collar=True
  Belt / Sash      — when has_sash=True or fit_style == "wrap"
  Side Pocket Bag  — when has_pockets=True

Silhouettes (fit_style):
  shift, sheath, a_line, fit_and_flare, wrap, bodycon, empire

Necklines:
  crew, round, scoop, v_neck, square, boat, sweetheart,
  halter, strapless, off_shoulder

Sleeve lengths:
  sleeveless, spaghetti, cap, short, three_quarter, long

Length categories:
  mini, above_knee, knee, midi, maxi
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.skirts import SKIRT_DART_SPLIT_B, SKIRT_DART_SPLIT_F, DartSpec, PieceSpec, split_waist_reduction

EASE_BUST = 4.0   # standard bust ease added to full bust circumference
_KAPPA = 0.5523   # Bézier quarter-circle approximation constant

# ── Fit-style parameter table ──────────────────────────────────────────────────
# bodice_suppress : cm the bodice side seam tapers inward from armhole to waist
# skirt_hem_mult  : multiplier of hip_qt for the skirt hem half-width
# skirt_no_darts  : True → skirt is gathered / elastic at waist (no sewn darts)
# drop_shoulder   : cm the shoulder tip extends beyond chest_qt (loose/casual)
# empire          : True → bodice ends at underbust; skirt attaches at empire seam
# shoulder_slope  : cm drop from neckline level to shoulder tip (y-axis, SVG down)
_FIT_PARAMS: dict[str, dict] = {
    "shift":         dict(bodice_suppress=0.0, skirt_hem_mult=1.05, skirt_no_darts=True,  drop_shoulder=0.5, empire=False, shoulder_slope=2.0),
    "sheath":        dict(bodice_suppress=2.5, skirt_hem_mult=0.90, skirt_no_darts=False, drop_shoulder=0.0, empire=False, shoulder_slope=0.5),
    "a_line":        dict(bodice_suppress=1.5, skirt_hem_mult=1.40, skirt_no_darts=False, drop_shoulder=0.0, empire=False, shoulder_slope=1.5),
    "fit_and_flare": dict(bodice_suppress=2.5, skirt_hem_mult=1.85, skirt_no_darts=True,  drop_shoulder=0.0, empire=False, shoulder_slope=0.5),
    "wrap":          dict(bodice_suppress=1.0, skirt_hem_mult=1.25, skirt_no_darts=False, drop_shoulder=0.0, empire=False, shoulder_slope=1.5),
    "bodycon":       dict(bodice_suppress=3.5, skirt_hem_mult=0.82, skirt_no_darts=False, drop_shoulder=0.0, empire=False, shoulder_slope=0.5),
    "empire":        dict(bodice_suppress=0.0, skirt_hem_mult=1.35, skirt_no_darts=True,  drop_shoulder=0.0, empire=True,  shoulder_slope=1.5),
}
_DEFAULT_FIT = _FIT_PARAMS["a_line"]

# ── Neckline depth extras (added to the base front neck depth = bust/10 + 2) ──
_NECKLINE_DEPTH_EXTRA: dict[str, float] = {
    "crew":        0.0,
    "round":       1.5,
    "scoop":       3.5,
    "v_neck":      10.0,
    "square":      1.5,
    "boat":       -0.5,
    "sweetheart":  2.5,
    "halter":      0.0,
    "strapless":   0.0,
    "off_shoulder": 0.5,
}

# Necklines whose CF opening is shaped as a cubic Bézier arc
_CURVED_NECKLINES = {"crew", "round", "scoop", "sweetheart"}

# ── Length category → waist-to-hem length in cm (None = use m.length_cm) ─────
_LENGTH_CM: dict[str, float | None] = {
    "mini":       42.0,
    "above_knee": 52.0,
    "knee":       60.0,
    "midi":       85.0,
    "maxi":       None,
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _rect_piece(name: str, w: float, h: float, cut_qty: int, sa: float, notes: str = "") -> PieceSpec:
    """Return a simple rectangular PieceSpec with a horizontal grain line."""
    return PieceSpec(
        name=name,
        outline=[Point(0.0, 0.0), Point(w, 0.0), Point(w, h), Point(0.0, h)],
        darts=[],
        grain_start=Point(w * 0.1, h / 2),
        grain_end=Point(w * 0.9, h / 2),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes=notes,
    )


def build_dress_block(
    m: Measurements,
    fit_style: str = "a_line",
    length_category: str = "midi",
    sleeve_length: str = "sleeveless",
    neckline: str = "round",
    closure_type: str = "center_back_zip",  # center_back_zip | side_zip | hook_and_eye | none
    has_collar: bool = False,
    has_sash: bool = False,
    has_pockets: bool = False,
    has_lining: bool = False,
    strap_style: str = "shoulder_seam",
    back_coverage: str = "full",
    front_opening: str = "closed",
) -> dict[str, PieceSpec]:
    """Return dress pattern pieces shaped by the analysed garment features.

    Silhouettes  : shift, sheath, a_line, fit_and_flare, wrap, bodycon, empire
    Necklines    : crew, round, scoop, v_neck, square, boat, sweetheart,
                   halter, strapless, off_shoulder
    Sleeve length: sleeveless, spaghetti, cap, short, three_quarter, long
    Length       : mini, above_knee, knee, midi, maxi
    Closure      : center_back_zip, side_zip, hook_and_eye, none
    """
    fit_style = (fit_style or "a_line").lower()
    neckline  = (neckline  or "round").lower()
    sleeve_length = (sleeve_length or "sleeveless").lower()

    # ── Construction topology ─────────────────────────────────────────────────
    # The dress bodice already models "halter"/"strapless" via the neckline; map the
    # structured strap_style onto it so both signals drive the same geometry.
    strap_style   = (strap_style or "shoulder_seam").lower()
    back_coverage = (back_coverage or "full").lower()
    front_opening = (front_opening or "closed").lower()
    if strap_style in ("halter_neck", "halter_tie") and neckline != "halter":
        neckline = "halter"
    elif strap_style == "strapless" and neckline != "strapless":
        neckline = "strapless"

    fp = _FIT_PARAMS.get(fit_style, _DEFAULT_FIT)
    is_empire = fp["empire"]

    # ── Resolve measurements ──────────────────────────────────────────────────
    bust = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    shoulder = m.shoulder_width_cm if m.shoulder_width_cm is not None else (bust / 4 + 7.5)
    arm_len = m.arm_length_cm if m.arm_length_cm is not None else 60.0
    W   = m.waist_cm
    H   = m.hip_cm
    wh  = m.waist_to_hip_cm
    sa  = m.seam_allowance_cm

    fixed_len = _LENGTH_CM.get(length_category)
    total_L = fixed_len if fixed_len is not None else m.length_cm
    total_L = max(total_L, 30.0)

    # ── Key bodice measurements (Aldrich) ─────────────────────────────────────
    chest_qt     = (bust + EASE_BUST) / 4
    shoulder_qt  = shoulder / 2
    back_neck_w  = bust / 10 + 1.0
    front_neck_w = back_neck_w
    arm_depth    = bust / 4 + 4.0          # vertical depth of armhole from shoulder level

    shoulder_slope  = fp["shoulder_slope"]
    drop_shoulder   = fp["drop_shoulder"]
    bodice_suppress = fp["bodice_suppress"]
    shoulder_tip_x  = shoulder_qt + drop_shoulder

    # Bodice height: empire ends below bust; standard ends at natural waist
    bodice_h = (arm_depth + 8.0) if is_empire else (arm_depth + 18.0)

    # Side seam at the bottom of the bodice (narrower for fitted styles)
    waist_side = chest_qt - bodice_suppress

    # Wrap: CF overlap extension
    wrap_extra = 12.0 if fit_style == "wrap" else 0.0

    # ── Neckline depth ────────────────────────────────────────────────────────
    depth_extra = _NECKLINE_DEPTH_EXTRA.get(neckline, 0.0)
    front_neck_depth = bust / 10 + 2.0 + depth_extra
    # Open front (plunge / deep V split): drop the CF opening toward the waistline.
    if front_opening in ("plunge", "deep_v_split"):
        front_neck_depth = max(front_neck_depth, bodice_h * 0.85)

    # ── Back Bodice ───────────────────────────────────────────────────────────
    if neckline == "strapless":
        # No shoulder seam: top edge is a straight band at armhole level
        back_bodice_outline: list[Point | CurveSegment] = [
            Point(0.0, arm_depth),
            Point(chest_qt, arm_depth),
            Point(waist_side if bodice_suppress > 0 else chest_qt, bodice_h),
            Point(0.0, bodice_h),
        ]
    elif bodice_suppress > 0.0:
        back_bodice_outline = [
            Point(0.0, 0.0),
            Point(back_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            Point(chest_qt, arm_depth),
            Point(waist_side, bodice_h),
            Point(0.0, bodice_h),
        ]
    else:
        back_bodice_outline = [
            Point(0.0, 0.0),
            Point(back_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            Point(chest_qt, arm_depth),
            Point(chest_qt, bodice_h),
            Point(0.0, bodice_h),
        ]

    back_bodice_grain_x = chest_qt / 2
    _back_bodice_closure = f"{closure_type.replace('_', ' ')} at CB" if closure_type != "none" else "no closure at CB"
    _bbn = len(back_bodice_outline)
    _back_bodice_labels = (
        {0: "neckline", 1: "side_seam", 2: "waist_seam", 3: "center_back"}
        if _bbn == 4 else
        {0: "neckline", 1: "shoulder", 2: "armhole", 3: "side_seam", 4: "waist_seam", 5: "center_back"}
    )
    back_bodice_spec = PieceSpec(
        name="Back Bodice",
        outline=back_bodice_outline,
        darts=[],
        grain_start=Point(back_bodice_grain_x, arm_depth * 0.5),
        grain_end=Point(back_bodice_grain_x, bodice_h * 0.85),
        cut_qty=2,
        on_fold=True,
        seam_allowance=sa,
        notes=f"back bodice panel cut on fold; {_back_bodice_closure}; sew to Front Bodice at shoulder seams and side seams; join to skirt at waist seam",
        edge_labels=_back_bodice_labels,
    )

    # ── Front Bodice ──────────────────────────────────────────────────────────
    # Side seam x at bodice hem — same rule as back
    f_waist_side = waist_side if bodice_suppress > 0.0 else chest_qt

    def _front_base_pts() -> list[Point | CurveSegment]:
        """Return the standard shoulder→armhole→hem path (appended after neckline pts)."""
        pts: list[Point | CurveSegment] = [
            Point(shoulder_tip_x, shoulder_slope),
            Point(chest_qt, arm_depth),
        ]
        if bodice_suppress > 0.0:
            pts.append(Point(f_waist_side, bodice_h))
        else:
            pts.append(Point(chest_qt, bodice_h))
        pts.append(Point(0.0, bodice_h))
        return pts

    if neckline == "strapless":
        front_bodice_outline: list[Point | CurveSegment] = [
            Point(0.0, arm_depth),
            Point(chest_qt, arm_depth),
            Point(f_waist_side, bodice_h),
            Point(0.0, bodice_h),
        ]
    elif neckline == "halter":
        # CF neck drops; strap point replaces shoulder seam
        strap_pt = Point(front_neck_w * 0.35, front_neck_depth * 0.5)
        front_bodice_outline = [
            Point(0.0, front_neck_depth),
            strap_pt,
            Point(chest_qt, arm_depth),
            Point(f_waist_side, bodice_h),
            Point(0.0, bodice_h),
        ]
    elif neckline == "off_shoulder":
        # Shallow neckline but shoulder tip extends wide; no standard neck shaping
        front_bodice_outline = [
            Point(0.0, shoulder_slope + 1.5),
            Point(shoulder_tip_x + 3.0, shoulder_slope * 0.5),
            Point(chest_qt, arm_depth),
            Point(f_waist_side, bodice_h),
            Point(0.0, bodice_h),
        ]
    elif neckline in _CURVED_NECKLINES:
        neck_curve_pt: Point | CurveSegment = CurveSegment(
            x=front_neck_w,
            y=0.0,
            cp1=Point(front_neck_w * _KAPPA, front_neck_depth),
            cp2=Point(front_neck_w, front_neck_depth * _KAPPA),
        )
        front_bodice_outline = [Point(0.0, front_neck_depth), neck_curve_pt] + _front_base_pts()
    elif neckline == "v_neck":
        front_bodice_outline = [
            Point(0.0, front_neck_depth),
            Point(front_neck_w, 0.0),
        ] + _front_base_pts()
    elif neckline == "square":
        front_bodice_outline = [
            Point(0.0, front_neck_depth),
            Point(front_neck_w, front_neck_depth),
            Point(front_neck_w, 0.0),
        ] + _front_base_pts()
    else:
        # boat and fallback
        front_bodice_outline = [
            Point(0.0, front_neck_depth),
            Point(front_neck_w, 0.0),
        ] + _front_base_pts()

    # Wrap: shift all x=0 outline points outward for CF overlap
    if wrap_extra > 0.0:
        front_bodice_outline = [
            Point(p.x + wrap_extra, p.y) if isinstance(p, Point) and p.x == 0.0 else p
            for p in front_bodice_outline
        ]
        front_bodice_on_fold = False
    else:
        front_bodice_on_fold = True

    # Bust dart (waist level) for fitted silhouettes
    front_bodice_darts: list[DartSpec] = []
    bust_dart_intake = max(0.0, chest_qt - W / 4 - 1.5)
    if bodice_suppress >= 2.0 and bust_dart_intake > 0.3:
        dart_depth_bodice = _clamp(8.0, 5.0, bodice_h * 0.55)
        dart_x = _clamp(
            chest_qt * 0.45,
            bust_dart_intake / 2 + 0.5,
            chest_qt - bust_dart_intake / 2 - 0.5,
        )
        front_bodice_darts.append(DartSpec(center_x=dart_x, width=bust_dart_intake, depth=dart_depth_bodice))

    _front_fold_note = "cut on fold at CF" if front_bodice_on_fold else "CF is open edge (wrap/closure)"
    _fbn = len(front_bodice_outline)
    if _fbn == 4:
        _front_bodice_labels = {0: "neckline", 1: "side_seam", 2: "waist_seam", 3: "center_front"}
    elif _fbn == 5:
        if neckline == "halter":
            _front_bodice_labels = {0: "neckline", 1: "armhole", 2: "side_seam", 3: "waist_seam", 4: "center_front"}
        else:
            _front_bodice_labels = {0: "shoulder", 1: "armhole", 2: "side_seam", 3: "waist_seam", 4: "center_front"}
    elif _fbn == 7:
        _front_bodice_labels = {0: "neckline", 1: "neckline", 2: "shoulder", 3: "armhole", 4: "side_seam", 5: "waist_seam", 6: "center_front"}
    else:
        _front_bodice_labels = {0: "neckline", 1: "shoulder", 2: "armhole", 3: "side_seam", 4: "waist_seam", 5: "center_front"}
    front_bodice_spec = PieceSpec(
        name="Front Bodice",
        outline=front_bodice_outline,
        darts=front_bodice_darts,
        grain_start=Point(chest_qt / 2, arm_depth * 0.5),
        grain_end=Point(chest_qt / 2, bodice_h * 0.85),
        cut_qty=2,
        on_fold=front_bodice_on_fold,
        seam_allowance=sa,
        notes=f"front bodice panel; {_front_fold_note}; sew to Back Bodice at shoulder seams and side seams; join to Front Skirt at waist seam",
        edge_labels=_front_bodice_labels,
    )

    # ── Skirt block ───────────────────────────────────────────────────────────
    # Dress lengths (category table and m.length_cm) are waist-to-hem, so the
    # skirt runs the full length from the natural waist; an empire skirt also
    # covers the gap between the underbust seam and the natural waist.
    # Empire: "waist" = underbust circ ≈ bust - 8 cm
    waist_drop = (arm_depth + 18.0) - bodice_h
    skirt_L = max(total_L + waist_drop, wh + 5.0)

    hip_qt = (H + 2.0) / 4          # quarter hip with standard ease

    # The skirt is sewn to the bodice, so each side's sewn skirt waist must equal
    # that side's sewn bodice waist (edge minus any bust dart), not the body waist.
    front_bodice_waist = f_waist_side - sum(d.width for d in front_bodice_darts)
    back_bodice_waist = waist_side if bodice_suppress > 0.0 else chest_qt
    skirt_w_qt_f = front_bodice_waist
    skirt_w_qt_b = back_bodice_waist

    suppress_skirt_darts = fp["skirt_no_darts"] or closure_type == "none"
    if suppress_skirt_darts:
        skirt_dart_intake_f = skirt_dart_intake_b = 0.0
    else:
        skirt_dart_intake_f, _ = split_waist_reduction(hip_qt - skirt_w_qt_f, *SKIRT_DART_SPLIT_F)
        skirt_dart_intake_b, _ = split_waist_reduction(hip_qt - skirt_w_qt_b, *SKIRT_DART_SPLIT_B)
    skirt_edge_f = skirt_w_qt_f + skirt_dart_intake_f
    skirt_edge_b = skirt_w_qt_b + skirt_dart_intake_b
    skirt_dart_depth_f  = _clamp(10.0, 6.0, wh * 0.75)
    skirt_dart_depth_b  = _clamp(13.0, 8.0, wh * 0.90)

    hem_x = hip_qt * fp["skirt_hem_mult"]

    # Knee control point: sheath and bodycon taper to knee then flare slightly
    knee_taper: float | None = 0.85 if fit_style in ("sheath", "bodycon") else None
    knee_y: float | None = wh + (skirt_L - wh) * 0.65 if knee_taper else None
    knee_x: float | None = hip_qt * knee_taper if knee_taper else None

    def _skirt_side_pts(w_qt: float, w_extra: float, h_extra: float) -> list[Point]:
        """Build the skirt outline for one half-panel."""
        pts = [
            Point(0.0, 0.0),
            Point(w_qt + w_extra, 0.0),
            Point(hip_qt + w_extra, wh),
        ]
        if knee_taper is not None:
            pts.append(Point(knee_x, knee_y))
        pts += [Point(hem_x + h_extra, skirt_L), Point(0.0, skirt_L)]
        return pts

    front_skirt_outline = _skirt_side_pts(skirt_edge_f, wrap_extra, wrap_extra)

    front_skirt_darts: list[DartSpec] = []
    if not suppress_skirt_darts and skirt_dart_intake_f > 0.1:
        dart_x = _clamp(skirt_edge_f * 0.40, skirt_dart_intake_f / 2 + 0.5, skirt_edge_f - skirt_dart_intake_f / 2 - 0.5)
        front_skirt_darts.append(DartSpec(center_x=dart_x, width=skirt_dart_intake_f, depth=skirt_dart_depth_f))

    _fsn = len(front_skirt_outline)
    front_skirt_spec = PieceSpec(
        name="Front Skirt",
        outline=front_skirt_outline,
        darts=front_skirt_darts,
        grain_start=Point(hip_qt / 2, wh * 0.25),
        grain_end=Point(hip_qt / 2, skirt_L * 0.85),
        cut_qty=2,
        on_fold=fit_style != "wrap",
        seam_allowance=sa,
        notes="front skirt panel; sew to Back Skirt at side seams; join to Front Bodice at waist seam",
        edge_labels={0: "waist_seam", **{i: "side_seam" for i in range(1, _fsn - 2)}, _fsn - 2: "hem", _fsn - 1: "center_front"},
    )

    back_skirt_outline = _skirt_side_pts(skirt_edge_b, 0.0, 0.0)

    back_skirt_darts: list[DartSpec] = []
    if not suppress_skirt_darts and skirt_dart_intake_b > 0.1:
        dw_each = skirt_dart_intake_b / 2
        d1x = _clamp(skirt_edge_b * 0.30, dw_each / 2 + 0.3, skirt_edge_b / 2 - dw_each / 2 - 0.3)
        d2x = _clamp(skirt_edge_b * 0.65, skirt_edge_b / 2 + dw_each / 2 + 0.3, skirt_edge_b - dw_each / 2 - 0.3)
        back_skirt_darts.append(DartSpec(center_x=d1x, width=dw_each, depth=skirt_dart_depth_b))
        back_skirt_darts.append(DartSpec(center_x=d2x, width=dw_each, depth=skirt_dart_depth_b))

    _bsn = len(back_skirt_outline)
    back_skirt_spec = PieceSpec(
        name="Back Skirt",
        outline=back_skirt_outline,
        darts=back_skirt_darts,
        grain_start=Point(hip_qt / 2, wh * 0.25),
        grain_end=Point(hip_qt / 2, skirt_L * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes="back skirt panel; sew to Front Skirt at side seams; join to Back Bodice at waist seam",
        edge_labels={0: "waist_seam", **{i: "side_seam" for i in range(1, _bsn - 2)}, _bsn - 2: "hem", _bsn - 1: "center_back"},
    )

    pieces: dict[str, PieceSpec] = {
        "front_bodice": front_bodice_spec,
        "front_skirt":  front_skirt_spec,
        "back_skirt":   back_skirt_spec,
    }
    # Backless dress: drop the back bodice; the halter straps + a waist tie hold it on.
    if back_coverage == "backless":
        pieces["waist_tie"] = _rect_piece(
            "Waist Tie", max(50.0, W * 0.75), 5.0, 2, sa,
            notes="waist tie (cut 2); fold lengthwise RS together, stitch and turn; attach at the "
                  "bodice side seams so the open back ties closed at the waist",
        )
    else:
        pieces["back_bodice"] = back_bodice_spec

    # ── Sleeve ────────────────────────────────────────────────────────────────
    cap_height = bust / 8
    cap_w_half = chest_qt - 1.0

    if sleeve_length == "spaghetti":
        strap_h = arm_len * 0.60
        pieces["spaghetti_strap"] = _rect_piece("Spaghetti Strap", 3.0, strap_h, 4, sa,
            notes="spaghetti strap (cut 4: 2 outer + 2 lining); sew outer to lining RS together, turn with a loop turner; attach to bodice at shoulder and back neckline")
    elif sleeve_length not in ("sleeveless",):
        if sleeve_length == "cap":
            actual_len = 6.0
        elif sleeve_length == "short":
            actual_len = 25.0
        elif sleeve_length == "three_quarter":
            actual_len = arm_len * 0.67
        else:  # "long"
            actual_len = arm_len

        total_sleeve_h = cap_height + actual_len
        _dress_sleeve_notes: dict[str, str] = {
            "cap":           "cap sleeve; set directly into armscye with minimal ease",
            "short":         "short set-in sleeve; sew sleeve seam first to form tube, then ease cap into armscye",
            "three_quarter": "three-quarter set-in sleeve; sew sleeve seam to form tube, ease cap into armscye",
            "long":          "set-in sleeve; sew sleeve seam first to form tube, then ease cap into armscye",
        }
        sleeve_spec = PieceSpec(
            name="Sleeve",
            outline=[
                Point(0.0, 0.0),
                Point(cap_w_half, cap_height),
                Point(cap_w_half - 2.0, total_sleeve_h),
                Point(0.0, total_sleeve_h),
            ],
            darts=[],
            grain_start=Point(cap_w_half / 2, cap_height * 0.5),
            grain_end=Point(cap_w_half / 2, total_sleeve_h * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=sa,
            notes=_dress_sleeve_notes.get(sleeve_length, _dress_sleeve_notes["long"]),
            edge_labels={0: "armhole", 1: "sleeve_seam", 2: "wrist", 3: "center_sleeve"},
        )
        pieces["sleeve"] = sleeve_spec

    # ── Bodice facing (strapless / halter) ────────────────────────────────────
    if neckline in ("strapless", "halter"):
        pieces["bodice_facing"] = _rect_piece("Bodice Facing", chest_qt, 6.0, 2, sa,
            notes=f"{'strapless' if neckline == 'strapless' else 'halter'} neckline facing; interface; sew to upper bodice edge RS together, understitch and turn to inside")

    # ── Collar ────────────────────────────────────────────────────────────────
    if has_collar:
        neck_circ = (back_neck_w + front_neck_w) * 2 + sa * 2
        pieces["collar"] = PieceSpec(
            name="Collar",
            outline=[Point(0.0, 0.0), Point(neck_circ, 0.0), Point(neck_circ, 4.0), Point(0.0, 4.0)],
            darts=[],
            grain_start=Point(neck_circ * 0.1, 2.0),
            grain_end=Point(neck_circ * 0.9, 2.0),
            cut_qty=2,
            on_fold=False,
            seam_allowance=sa,
            notes="dress collar; interface outer layer; sew outer to under collar RS together, turn; attach to neckline and slip-stitch inner edge",
        )

    # ── Belt / Sash ───────────────────────────────────────────────────────────
    if has_sash or fit_style == "wrap":
        sash_w = max(30.0, total_L * 0.45)
        pieces["belt_sash"] = _rect_piece("Belt / Sash", sash_w, 8.0, 2, sa,
            notes="belt/sash strip; sew long edges RS together, turn right side out; tie at waist or attach at side seams")

    # ── Side pocket bag ───────────────────────────────────────────────────────
    if has_pockets:
        bag_w = max(10.0, hip_qt * 0.60)
        pieces["pocket_bag"] = _rect_piece("Side Pocket Bag", bag_w, 16.0, 2, sa,
            notes="in-seam side pocket bag; insert into skirt side seam before sewing Front Skirt to Back Skirt")

    return pieces
