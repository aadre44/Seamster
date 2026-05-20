"""Shirt / blouse base block (Aldrich parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Origin: x=0 is CB/CF fold edge; y=0 is shoulder/nape level
  - y increases toward hem

Pieces produced depend on analyzed features:
  - Back Bodice and Front Bodice are always produced.
  - Sleeve is produced unless sleeve_length == "sleeveless".
  - Collar is produced when has_collar=True.
  - Cuffs are produced when has_cuffs=True and sleeve has a wrist opening.
  - When has_placket=True the front is cut off-fold with a 3 cm CF overlap.

Fit styles affect bodice geometry:
  - slim / fitted: tapered side seams, tighter armhole, no drop shoulder
  - regular / relaxed: moderate shaping, standard construction
  - boxy: straight sides, extended drop shoulder, deeper armhole
  - oversized: extreme drop shoulder, maximum ease, straight sides
  - athletic: tight waist, wide shoulders, no drop shoulder
  - longline: standard shaping, extended body length

Necklines supported:
  crew, round, scoop, v_neck, square, polo, boat, mandarin,
  turtleneck, mock_turtleneck, henley, off_shoulder, keyhole

Sleeve types supported:
  sleeveless, cap, short, flutter, three_quarter, bell,
  puff_short, long, puff_long
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.skirts import PieceSpec

EASE_CHEST = 6.0      # standard chest/bust ease added to the full chest circumference
_PLACKET_WIDTH = 3.0  # cm of CF overlap strip added when has_placket=True
_COLLAR_HEIGHT = 4.0  # cm stand-collar height
_CUFF_HEIGHT = 6.0    # cm cuff height
_RIB_COLLAR_H = 5.0   # cm flat height of rib collar band (folds to ~2.5 cm finished)

# Bezier "magic number" for approximating a quarter-circle arc
_KAPPA = 0.5523

# Necklines that use a curved (convex) opening rather than a pointed/straight edge
_CURVED_NECKLINES = {"crew", "round", "scoop", "keyhole"}


# Per-silhouette geometry parameters.
# shoulder_slope : cm drop from neckline level to shoulder tip
# armhole_extra  : cm added to the base arm_depth (chest/4 + 4)
# waist_suppress : how much narrower the side seam is at waist vs chest quarter
# drop_shoulder  : cm the shoulder tip extends beyond chest_qt toward the arm
_FIT_PARAMS: dict[str, dict] = {
    "slim":      dict(shoulder_slope=0.5,  armhole_extra=-1.0, waist_suppress=3.0, drop_shoulder=0.0),
    "fitted":    dict(shoulder_slope=0.5,  armhole_extra=-0.5, waist_suppress=2.0, drop_shoulder=0.0),
    "regular":   dict(shoulder_slope=1.5,  armhole_extra= 0.0, waist_suppress=1.0, drop_shoulder=0.0),
    "relaxed":   dict(shoulder_slope=2.0,  armhole_extra= 1.0, waist_suppress=0.0, drop_shoulder=0.0),
    "boxy":      dict(shoulder_slope=2.5,  armhole_extra= 2.0, waist_suppress=0.0, drop_shoulder=1.5),
    "oversized": dict(shoulder_slope=3.5,  armhole_extra= 3.0, waist_suppress=0.0, drop_shoulder=3.0),
    "athletic":  dict(shoulder_slope=1.0,  armhole_extra=-0.5, waist_suppress=3.0, drop_shoulder=0.0),
    "longline":  dict(shoulder_slope=1.5,  armhole_extra= 0.0, waist_suppress=0.5, drop_shoulder=0.0),
}
_DEFAULT_FIT = _FIT_PARAMS["regular"]


def build_shirt_block(
    m: Measurements,
    chest_ease_extra: float = 0.0,
    fit_style: str = "regular",
    sleeve_length: str = "long",
    neckline: str = "crew",
    has_placket: bool = False,
    has_collar: bool = False,
    has_cuffs: bool = False,
    has_ribbed_collar: bool = False,
) -> dict[str, PieceSpec]:
    """Return shirt pattern pieces shaped by the analyzed garment features.

    chest_ease_extra : adjusts EASE_CHEST for different silhouettes.
    fit_style        : controls bodice shape (slope, suppression, drop shoulder).
    sleeve_length    : sleeveless | cap | short | flutter | three_quarter | bell |
                       puff_short | long | puff_long
    neckline         : crew | round | scoop | v_neck | square | polo | boat |
                       mandarin | turtleneck | mock_turtleneck | henley |
                       off_shoulder | keyhole
    has_placket      : front piece is off-fold with a 3 cm CF overlap strip
    has_collar       : add a rectangular stand collar piece
    has_cuffs        : add rectangular cuff pieces (only when wrist opening exists)
    """
    # ── Resolve optional measurements ────────────────────────────────────────
    chest = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    shoulder = m.shoulder_width_cm if m.shoulder_width_cm is not None else (chest / 4 + 7.5)
    arm_length = m.arm_length_cm if m.arm_length_cm is not None else 60.0
    W = m.waist_cm
    L = m.length_cm

    # ── Fit-style parameters ──────────────────────────────────────────────────
    fit_style = (fit_style or "regular").lower()
    fp = _FIT_PARAMS.get(fit_style, _DEFAULT_FIT)
    shoulder_slope = fp["shoulder_slope"]
    armhole_extra  = fp["armhole_extra"]
    waist_suppress = fp["waist_suppress"]
    drop_shoulder  = fp["drop_shoulder"]

    # ── Quarter / key measurements ────────────────────────────────────────────
    total_ease = EASE_CHEST + chest_ease_extra
    chest_qt = (chest + total_ease) / 4

    shoulder_qt = shoulder / 2
    back_neck_w = chest / 10 + 1.0
    front_neck_w = back_neck_w

    arm_depth = chest / 4 + 4.0 + armhole_extra
    waist_y = arm_depth + 18.0

    # Side-seam width at waist level (narrower for fitted styles)
    waist_side_b = chest_qt - waist_suppress
    waist_side_f = chest_qt - waist_suppress

    cap_height = chest / 8
    cap_w_half = chest_qt - 1.0

    # ── Neckline depth and shape ──────────────────────────────────────────────
    neckline = (neckline or "crew").lower()

    if neckline == "crew":
        front_neck_depth = chest / 10 + 2.0
    elif neckline == "round":
        front_neck_depth = chest / 10 + 3.5
        front_neck_w = back_neck_w * 1.1
    elif neckline == "scoop":
        front_neck_depth = chest / 10 + 5.5
        front_neck_w = back_neck_w * 1.3
    elif neckline == "v_neck":
        front_neck_depth = chest / 10 + 12.0
    elif neckline == "square":
        front_neck_depth = chest / 10 + 3.5
        front_neck_w = back_neck_w * 1.2
    elif neckline == "polo":
        front_neck_depth = chest / 10 + 1.0
    elif neckline == "boat":
        front_neck_depth = chest / 10 + 1.5
        front_neck_w = chest / 7
    elif neckline == "mandarin":
        front_neck_depth = chest / 10 + 1.0
    elif neckline in ("turtleneck", "mock_turtleneck"):
        front_neck_depth = chest / 10 + 0.5
    elif neckline == "henley":
        front_neck_depth = chest / 10 + 2.0
    elif neckline == "off_shoulder":
        front_neck_depth = shoulder_slope + 2.0
        front_neck_w = shoulder_qt
    elif neckline == "keyhole":
        front_neck_depth = chest / 10 + 2.5
    else:
        front_neck_depth = chest / 10 + 2.0

    # ── Shoulder tip x position (drop shoulder shifts it outward) ─────────────
    shoulder_tip_x = shoulder_qt + drop_shoulder

    # ── Armhole curve (shoulder tip → armscye): used on both bodices ──────────
    # CurveSegment means the edge arriving AT this vertex is a bezier.
    # cp1 is near the shoulder (going mostly downward/inward), cp2 is near the
    # armscye (arriving from slightly outside the side seam).
    _armhole_pt: Point | CurveSegment = CurveSegment(
        x=chest_qt, y=arm_depth,
        cp1=Point(shoulder_tip_x - 0.4, shoulder_slope + (arm_depth - shoulder_slope) * 0.45),
        cp2=Point(chest_qt + 1.5, arm_depth - (arm_depth - shoulder_slope) * 0.12),
    )

    # ── Back Bodice ───────────────────────────────────────────────────────────
    if waist_suppress == 0.0:
        # Straight side seam: no intermediate waist point
        back_outline = [
            Point(0.0, 0.0),
            Point(back_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            _armhole_pt,
            Point(chest_qt, L),
            Point(0.0, L),
        ]
    else:
        back_outline = [
            Point(0.0, 0.0),
            Point(back_neck_w, 0.0),
            Point(shoulder_tip_x, shoulder_slope),
            _armhole_pt,
            Point(waist_side_b, waist_y),
            Point(W / 4, L),
            Point(0.0, L),
        ]

    back_grain_x = chest_qt / 2
    back_spec = PieceSpec(
        name="Back Bodice",
        outline=back_outline,
        darts=[],
        grain_start=Point(back_grain_x, arm_depth),
        grain_end=Point(back_grain_x, L * 0.85),
        cut_qty=2,
        on_fold=True,
        seam_allowance=m.seam_allowance_cm,
    )

    # ── Front Bodice ──────────────────────────────────────────────────────────
    # For curved necklines the shoulder-side neck point is reached via a bezier
    # curve from the CF depth point, giving a smooth crew/round/scoop opening.
    if neckline in _CURVED_NECKLINES:
        neck_shoulder_pt: Point | CurveSegment = CurveSegment(
            x=front_neck_w,
            y=0.0,
            cp1=Point(front_neck_w * _KAPPA, front_neck_depth),
            cp2=Point(front_neck_w, front_neck_depth * _KAPPA),
        )
    else:
        neck_shoulder_pt = Point(front_neck_w, 0.0)

    if neckline == "v_neck":
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(W / 4 + 1.0, L),
                Point(0.0, L),
            ]
    elif neckline == "square":
        # Extra corner point creates the horizontal neckline edge
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                Point(front_neck_w, front_neck_depth),
                Point(front_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                Point(front_neck_w, front_neck_depth),
                Point(front_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(W / 4 + 1.0, L),
                Point(0.0, L),
            ]
    else:
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(W / 4 + 1.0, L),
                Point(0.0, L),
            ]

    # Button placket: shift CF edge outward; piece is cut off-fold
    if has_placket:
        front_outline = [
            Point(p.x + _PLACKET_WIDTH, p.y) if p.x == 0.0 else p
            for p in front_outline
        ]
        front_on_fold = False
        front_cut_qty = 2
    else:
        front_on_fold = True
        front_cut_qty = 2

    front_grain_x = chest_qt / 2
    front_spec = PieceSpec(
        name="Front Bodice",
        outline=front_outline,
        darts=[],
        grain_start=Point(front_grain_x, arm_depth),
        grain_end=Point(front_grain_x, L * 0.85),
        cut_qty=front_cut_qty,
        on_fold=front_on_fold,
        seam_allowance=m.seam_allowance_cm,
    )

    pieces: dict[str, PieceSpec] = {"back_bodice": back_spec, "front_bodice": front_spec}

    # ── Sleeve ────────────────────────────────────────────────────────────────
    sleeve_length = (sleeve_length or "long").lower()

    if sleeve_length == "sleeveless":
        pass
    else:
        # Determine sleeve length in cm and flare style
        flare_wrist: float | None = None  # None = standard taper; float = explicit wrist width

        if sleeve_length == "cap":
            actual_sleeve_len = 6.0
        elif sleeve_length == "short":
            actual_sleeve_len = 25.0
        elif sleeve_length == "flutter":
            actual_sleeve_len = 12.0
            flare_wrist = cap_w_half + 4.0
        elif sleeve_length == "three_quarter":
            actual_sleeve_len = arm_length * 0.67
        elif sleeve_length == "bell":
            actual_sleeve_len = arm_length
            flare_wrist = cap_w_half + 8.0
        elif sleeve_length == "puff_short":
            actual_sleeve_len = 18.0
            # Wider cap for gathering; taper back at hem
            cap_w_half = cap_w_half * 1.5
        elif sleeve_length == "puff_long":
            actual_sleeve_len = arm_length
            cap_w_half = cap_w_half * 1.5
        else:  # "long"
            actual_sleeve_len = arm_length

        total_sleeve_h = cap_height + actual_sleeve_len

        # Sleeve cap: curved dome from crown (0, 0) to underarm edge (cap_w_half, cap_height)
        _cap_curve = CurveSegment(
            x=cap_w_half, y=cap_height,
            cp1=Point(cap_w_half * 0.28, cap_height * 0.04),
            cp2=Point(cap_w_half * 0.88, cap_height * 0.45),
        )
        if flare_wrist is not None:
            sleeve_outline: list[Point | CurveSegment] = [
                Point(0.0, 0.0),
                _cap_curve,
                Point(flare_wrist, total_sleeve_h),
                Point(0.0, total_sleeve_h),
            ]
        else:
            sleeve_outline = [
                Point(0.0, 0.0),
                _cap_curve,
                Point(cap_w_half - 2.0, total_sleeve_h),
                Point(0.0, total_sleeve_h),
            ]

        sleeve_grain_x = cap_w_half / 2
        sleeve_spec = PieceSpec(
            name="Sleeve",
            outline=sleeve_outline,
            darts=[],
            grain_start=Point(sleeve_grain_x, cap_height * 0.5),
            grain_end=Point(sleeve_grain_x, total_sleeve_h * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
        )
        pieces["sleeve"] = sleeve_spec

        # ── Cuffs (long / three_quarter only, not flared sleeves) ─────────────
        if has_cuffs and sleeve_length in ("long", "three_quarter"):
            wrist_w = (cap_w_half - 2.0) * 2
            cuff_outline = [
                Point(0.0, 0.0),
                Point(wrist_w, 0.0),
                Point(wrist_w, _CUFF_HEIGHT),
                Point(0.0, _CUFF_HEIGHT),
            ]
            cuff_spec = PieceSpec(
                name="Cuff",
                outline=cuff_outline,
                darts=[],
                grain_start=Point(wrist_w * 0.1, _CUFF_HEIGHT / 2),
                grain_end=Point(wrist_w * 0.9, _CUFF_HEIGHT / 2),
                cut_qty=2,
                on_fold=False,
                seam_allowance=m.seam_allowance_cm,
            )
            pieces["cuff"] = cuff_spec

    # ── Collar ────────────────────────────────────────────────────────────────
    if has_collar:
        neck_circumference = (back_neck_w + front_neck_w) * 2
        collar_w = neck_circumference + m.seam_allowance_cm * 2
        collar_outline = [
            Point(0.0, 0.0),
            Point(collar_w, 0.0),
            Point(collar_w, _COLLAR_HEIGHT),
            Point(0.0, _COLLAR_HEIGHT),
        ]
        collar_spec = PieceSpec(
            name="Collar",
            outline=collar_outline,
            darts=[],
            grain_start=Point(collar_w * 0.1, _COLLAR_HEIGHT / 2),
            grain_end=Point(collar_w * 0.9, _COLLAR_HEIGHT / 2),
            cut_qty=2,
            on_fold=False,
            seam_allowance=m.seam_allowance_cm,
        )
        pieces["collar"] = collar_spec

    # ── Ribbed Collar Band ────────────────────────────────────────────────────
    # Only generated when the vision analysis explicitly detected one.
    # Cut slightly shorter than the neck opening so the rib stretches when sewn in.
    if has_ribbed_collar and not has_collar:
        neck_circ = (back_neck_w + front_neck_w) * 2
        rib_w = neck_circ * 0.9  # rib stretches ~10% when sewn to opening
        rib_outline = [
            Point(0.0, 0.0),
            Point(rib_w, 0.0),
            Point(rib_w, _RIB_COLLAR_H),
            Point(0.0, _RIB_COLLAR_H),
        ]
        rib_spec = PieceSpec(
            name="Ribbed Collar Band",
            outline=rib_outline,
            darts=[],
            grain_start=Point(rib_w * 0.1, _RIB_COLLAR_H / 2),
            grain_end=Point(rib_w * 0.9, _RIB_COLLAR_H / 2),
            cut_qty=1,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
        )
        pieces["rib_collar"] = rib_spec

    # ── Turtleneck / Mock Turtleneck Band ─────────────────────────────────────
    if neckline in ("turtleneck", "mock_turtleneck"):
        tube_h = 20.0 if neckline == "turtleneck" else 12.0
        neck_circ = (back_neck_w + front_neck_w) * 2
        band_w = neck_circ
        band_outline = [
            Point(0.0, 0.0),
            Point(band_w, 0.0),
            Point(band_w, tube_h),
            Point(0.0, tube_h),
        ]
        band_name = "Turtleneck Band" if neckline == "turtleneck" else "Mock Turtleneck Band"
        band_spec = PieceSpec(
            name=band_name,
            outline=band_outline,
            darts=[],
            grain_start=Point(band_w * 0.1, tube_h / 2),
            grain_end=Point(band_w * 0.9, tube_h / 2),
            cut_qty=1,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
        )
        pieces["neck_band"] = band_spec

    # ── Henley Placket Strip ──────────────────────────────────────────────────
    if neckline == "henley":
        placket_h = front_neck_depth * 0.7
        placket_w = 4.0
        henley_outline = [
            Point(0.0, 0.0),
            Point(placket_w, 0.0),
            Point(placket_w, placket_h),
            Point(0.0, placket_h),
        ]
        henley_spec = PieceSpec(
            name="Henley Placket",
            outline=henley_outline,
            darts=[],
            grain_start=Point(placket_w * 0.1, placket_h / 2),
            grain_end=Point(placket_w * 0.9, placket_h / 2),
            cut_qty=1,
            on_fold=False,
            seam_allowance=m.seam_allowance_cm,
        )
        pieces["henley_placket"] = henley_spec

    return pieces
