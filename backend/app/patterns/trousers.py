"""Trouser / pants base block (Aldrich parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Origin: x=0 is the CF/CB crotch-seam edge; y=0 is the waist line
  - y increases toward ankle

Pieces produced: Front Leg, Back Leg, and conditionally: fly_facing, fly_shield,
pocket_bag, back_pocket, cargo_pocket, cargo_pocket_flap, cuff_band, ankle_elastic.
A waistband is added separately by the pattern engine using _make_waistband().

Crotch seam geometry
--------------------
The front and back crotch seams are cubic Bézier curves (CurveSegment) rather than
straight-line corners.  The curve sweeps from the inseam (at crotch level) around the
crotch extension to meet the CF/CB line at rise height.  The depth of the arc below the
rise line is parameterised per fit-style:

  - Tighter fits (skinny/slim) → shallower arc → less fabric pooling at the crotch
  - Roomier fits (palazzo/jogger) → deeper arc → more ease for movement and sitting

cp1 directs the curve rightward from the inseam; cp2 makes it arrive vertically at CF/CB
so the junction is smooth with the straight CF/CB edge above it.

Darts work correctly here: _serialise_piece() places dart legs at y=0,
which IS the top edge (waist line) for trouser panels. ✓
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.skirts import DartSpec, PieceSpec

# ── Fit-style parameter table ─────────────────────────────────────────────────
# hip_ease        : added to full hip before dividing by 4
# thigh_mult      : multiplier of hip_qt at crotch/thigh level
# knee_mult       : multiplier of hip_qt at knee level
# ankle_half_f/b  : absolute half-width at ankle for front/back leg (cm)
# crotch_depth_f  : how far (cm) the front crotch arc dips below the rise line
# crotch_depth_b  : how far (cm) the back crotch arc dips below the rise line
#                   (deeper = more seat ease for sitting)
_FIT_PARAMS: dict[str, dict] = {
    "skinny":    dict(hip_ease=-2.0, thigh_mult=0.90, knee_mult=0.85, ankle_half_f=7.0,  ankle_half_b=8.0,  crotch_depth_f=1.0, crotch_depth_b=2.0),
    "slim":      dict(hip_ease=-1.0, thigh_mult=0.93, knee_mult=0.88, ankle_half_f=9.0,  ankle_half_b=10.0, crotch_depth_f=1.2, crotch_depth_b=2.5),
    "cigarette": dict(hip_ease=0.0,  thigh_mult=0.95, knee_mult=0.90, ankle_half_f=9.5,  ankle_half_b=10.5, crotch_depth_f=1.2, crotch_depth_b=2.5),
    "fitted":    dict(hip_ease=0.0,  thigh_mult=0.97, knee_mult=0.93, ankle_half_f=10.0, ankle_half_b=11.0, crotch_depth_f=1.3, crotch_depth_b=2.8),
    "regular":   dict(hip_ease=2.0,  thigh_mult=1.00, knee_mult=0.95, ankle_half_f=11.0, ankle_half_b=12.0, crotch_depth_f=1.5, crotch_depth_b=3.0),
    "relaxed":   dict(hip_ease=3.0,  thigh_mult=1.05, knee_mult=1.00, ankle_half_f=12.0, ankle_half_b=13.0, crotch_depth_f=1.8, crotch_depth_b=3.5),
    "wide_leg":  dict(hip_ease=6.0,  thigh_mult=1.20, knee_mult=1.30, ankle_half_f=18.0, ankle_half_b=19.0, crotch_depth_f=2.0, crotch_depth_b=3.5),
    "flared":    dict(hip_ease=2.0,  thigh_mult=0.95, knee_mult=1.10, ankle_half_f=16.0, ankle_half_b=17.0, crotch_depth_f=1.5, crotch_depth_b=3.0),
    "bootcut":   dict(hip_ease=2.0,  thigh_mult=0.95, knee_mult=0.95, ankle_half_f=13.0, ankle_half_b=14.0, crotch_depth_f=1.5, crotch_depth_b=3.0),
    "palazzo":   dict(hip_ease=8.0,  thigh_mult=1.35, knee_mult=1.45, ankle_half_f=22.0, ankle_half_b=23.0, crotch_depth_f=2.0, crotch_depth_b=4.0),
    "jogger":    dict(hip_ease=3.0,  thigh_mult=1.05, knee_mult=1.00, ankle_half_f=7.0,  ankle_half_b=8.0,  crotch_depth_f=1.8, crotch_depth_b=4.0),
}

# ── Rise style deltas (added to resolved rise measurement) ────────────────────
_RISE_DELTA: dict[str, float] = {
    "low_rise":        -4.0,
    "mid_rise":         0.0,
    "high_rise":        3.0,
    "ultra_high_rise":  6.0,
}

# ── Length category → fixed inseam (None = use measurement) ──────────────────
_LENGTH_INSEAM: dict[str, float | None] = {
    "shorts":      10.0,
    "bermuda":     25.0,
    "capri":       50.0,
    "ankle":       70.0,
    "full_length": None,
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _rect_piece(name: str, w: float, h: float, cut_qty: int, sa: float) -> PieceSpec:
    """Return a simple rectangular PieceSpec with a horizontal grain line."""
    outline = [
        Point(0.0, 0.0),
        Point(w,   0.0),
        Point(w,   h),
        Point(0.0, h),
    ]
    return PieceSpec(
        name=name,
        outline=outline,
        darts=[],
        grain_start=Point(w * 0.2, h / 2),
        grain_end=Point(w * 0.8, h / 2),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
    )


def build_trousers_block(
    m: Measurements,
    ankle_ease_extra: float = 0.0,      # legacy shim — ignored when fit_style provided explicitly
    fit_style: str = "regular",
    rise_style: str = "mid_rise",
    length_category: str = "full_length",
    closure_type: str = "zip_fly",      # zip_fly | button_fly | elastic_waist | side_zip
    has_fly_shield: bool = False,
    has_front_pockets: bool = False,
    has_back_pockets: bool = False,
    has_cargo_pocket: bool = False,
    has_cuff_band: bool = False,
    has_ankle_elastic: bool = False,
    has_belt_loops: bool = False,       # indicator only — no geometry piece
) -> dict[str, PieceSpec]:
    """Return front/back legs plus conditional detail pieces.

    Fit styles:  skinny, slim, cigarette, fitted, regular, relaxed,
                 wide_leg, flared, bootcut, palazzo, jogger
    Rise styles: low_rise, mid_rise, high_rise, ultra_high_rise
    Length:      shorts, bermuda, capri, ankle, full_length
    Closure:     zip_fly, button_fly, elastic_waist, side_zip
    """
    fp = _FIT_PARAMS.get(fit_style, _FIT_PARAMS["regular"])

    # ── Resolve measurements ──────────────────────────────────────────────────
    rise_delta = _RISE_DELTA.get(rise_style, 0.0)
    rise = (m.rise_cm if m.rise_cm is not None else (m.hip_cm / 4)) + rise_delta

    fixed_inseam = _LENGTH_INSEAM.get(length_category)
    inseam = fixed_inseam if fixed_inseam is not None else (m.inseam_cm if m.inseam_cm is not None else 76.0)

    W = m.waist_cm
    H = m.hip_cm
    wh = m.waist_to_hip_cm
    sa = m.seam_allowance_cm
    total_length = rise + inseam

    # ── Quarter / key measurements ────────────────────────────────────────────
    hip_qt = (H + fp["hip_ease"]) / 4

    waist_qt_f = W / 4 + 0.5           # front (slightly wider — Aldrich balance)
    waist_qt_b = W / 4 - 0.5           # back  (slightly narrower)

    # Crotch extensions (horizontal distance at crotch level)
    crotch_ext_f = H / 16 + 0.5        # front: narrower (≈ 6–7 cm for H=94)
    crotch_ext_b = H / 8 + 1.0         # back: wider for seat ease (≈ 13 cm for H=94)

    hip_qt_b = hip_qt + 1.5            # back gets extra seat ease

    # Dart intakes
    dart_intake_f = hip_qt - waist_qt_f
    dart_intake_b = hip_qt_b - waist_qt_b

    # Thigh widths (at crotch level)
    thigh_half_f = hip_qt * fp["thigh_mult"]
    thigh_half_b = hip_qt_b * fp["thigh_mult"]

    # Knee level (60% of inseam below crotch) — intermediate control point
    knee_y = rise + inseam * 0.60
    knee_half_f = hip_qt * fp["knee_mult"]
    knee_half_b = hip_qt_b * fp["knee_mult"]

    # Ankle widths
    ankle_half_f = fp["ankle_half_f"]
    ankle_half_b = fp["ankle_half_b"]

    # Grain centrelines
    grain_x_f = (crotch_ext_f + hip_qt) / 2
    grain_x_b = (crotch_ext_b + hip_qt_b) / 2

    # ── Crotch curve parameters ───────────────────────────────────────────────
    # Depth below the rise line (varies with fit — affects seating comfort and silhouette)
    crotch_depth_f = fp["crotch_depth_f"]
    crotch_depth_b = fp["crotch_depth_b"]

    # x-position of the inseam where it meets the start of the crotch arc.
    # For most fits this clamps to a small positive value; the arc then sweeps
    # rightward to crotch_ext where it meets the CF/CB edge.
    crotch_inseam_x_f = max(0.3, grain_x_f - thigh_half_f)
    crotch_inseam_x_b = max(0.3, grain_x_b - thigh_half_b)

    # ── Dart suppression for elastic waist / jogger ───────────────────────────
    suppress_darts = closure_type == "elastic_waist"

    # ── Front Leg ─────────────────────────────────────────────────────────────
    # The crotch seam ([8]→[9]) is a cubic Bézier arc:
    #   [8] = deepest point of the crotch arc (at rise + depth below waist)
    #   [9] = CF at rise level (CurveSegment endpoint)
    #   cp1 sweeps the arc rightward from [8]; cp2 makes it arrive vertically at [9]
    front_outline: list[Point | CurveSegment] = [
        Point(crotch_ext_f, 0.0),                                # [0] CF at waist
        Point(crotch_ext_f + waist_qt_f, 0.0),                   # [1] SS at waist
        Point(crotch_ext_f + hip_qt, wh),                        # [2] SS at hip
        Point(crotch_ext_f + thigh_half_f, rise),                # [3] SS at thigh
        Point(grain_x_f + knee_half_f, knee_y),                  # [4] SS at knee
        Point(grain_x_f + ankle_half_f, total_length),           # [5] SS at ankle
        Point(max(0.5, grain_x_f - ankle_half_f), total_length), # [6] inseam at ankle
        Point(max(0.5, grain_x_f - knee_half_f), knee_y),        # [7] inseam at knee
        Point(crotch_inseam_x_f, rise + crotch_depth_f),         # [8] crotch arc deepest point
        CurveSegment(                                              # [9] CF at crotch junction
            x=crotch_ext_f,
            y=rise,
            cp1=Point(crotch_inseam_x_f + crotch_ext_f * 0.6, rise + crotch_depth_f),
            cp2=Point(crotch_ext_f, rise + crotch_depth_f * 0.6),
        ),
    ]

    front_darts: list[DartSpec] = []
    if not suppress_darts and dart_intake_f > 0.5:
        dart_x = _clamp(
            crotch_ext_f + waist_qt_f * 0.40,
            crotch_ext_f + dart_intake_f / 2 + 0.5,
            crotch_ext_f + waist_qt_f - dart_intake_f / 2 - 0.5,
        )
        front_darts.append(DartSpec(
            center_x=dart_x,
            width=dart_intake_f,
            depth=_clamp(9.0, 6.0, wh * 0.70),
        ))

    _front_dart_note = "" if suppress_darts else "; sew front waist dart(s) before attaching waistband"
    front_spec = PieceSpec(
        name="Front Leg",
        outline=front_outline,
        darts=front_darts,
        grain_start=Point(grain_x_f, wh * 0.3),
        grain_end=Point(grain_x_f, total_length * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes=f"front trouser leg{_front_dart_note}; inseam joins to Back Leg at crotch; outseam joins back at side seam",
        edge_labels={0: "waist", 1: "side_seam", 2: "side_seam", 3: "side_seam", 4: "side_seam", 5: "hem", 6: "inseam", 7: "inseam", 8: "crotch", 9: "center_front"},
    )

    # ── Back Leg ──────────────────────────────────────────────────────────────
    # Same curved crotch logic; back arc is deeper (more seat ease).
    back_outline: list[Point | CurveSegment] = [
        Point(crotch_ext_b, 0.0),                                # [0] CB at waist
        Point(crotch_ext_b + waist_qt_b, 0.0),                   # [1] SS at waist
        Point(crotch_ext_b + hip_qt_b, wh),                      # [2] SS at hip
        Point(crotch_ext_b + thigh_half_b, rise),                # [3] SS at thigh
        Point(grain_x_b + knee_half_b, knee_y),                  # [4] SS at knee
        Point(grain_x_b + ankle_half_b, total_length),           # [5] SS at ankle
        Point(max(0.5, grain_x_b - ankle_half_b), total_length), # [6] inseam at ankle
        Point(max(0.5, grain_x_b - knee_half_b), knee_y),        # [7] inseam at knee
        Point(crotch_inseam_x_b, rise + crotch_depth_b),         # [8] crotch arc deepest point
        CurveSegment(                                              # [9] CB at crotch junction
            x=crotch_ext_b,
            y=rise,
            cp1=Point(crotch_inseam_x_b + crotch_ext_b * 0.6, rise + crotch_depth_b),
            cp2=Point(crotch_ext_b, rise + crotch_depth_b * 0.6),
        ),
    ]

    back_darts: list[DartSpec] = []
    if not suppress_darts and dart_intake_b > 0.5:
        dw_each = dart_intake_b / 2
        dart_depth_b = _clamp(12.0, 8.0, wh * 0.85)
        dart1_x = _clamp(
            crotch_ext_b + waist_qt_b * 0.30,
            crotch_ext_b + dw_each / 2 + 0.3,
            crotch_ext_b + waist_qt_b / 2 - dw_each / 2 - 0.3,
        )
        dart2_x = _clamp(
            crotch_ext_b + waist_qt_b * 0.65,
            crotch_ext_b + waist_qt_b / 2 + dw_each / 2 + 0.3,
            crotch_ext_b + waist_qt_b - dw_each / 2 - 0.3,
        )
        back_darts.append(DartSpec(center_x=dart1_x, width=dw_each, depth=dart_depth_b))
        back_darts.append(DartSpec(center_x=dart2_x, width=dw_each, depth=dart_depth_b))

    _back_dart_note = "" if suppress_darts else "; sew back waist dart(s) before attaching waistband"
    back_spec = PieceSpec(
        name="Back Leg",
        outline=back_outline,
        darts=back_darts,
        grain_start=Point(grain_x_b, wh * 0.3),
        grain_end=Point(grain_x_b, total_length * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes=f"back trouser leg with curved seat{_back_dart_note}; deeper back rise; inseam joins Front Leg; outseam forms side seam",
        edge_labels={0: "waist", 1: "side_seam", 2: "side_seam", 3: "side_seam", 4: "side_seam", 5: "hem", 6: "inseam", 7: "inseam", 8: "crotch", 9: "center_back"},
    )

    pieces: dict[str, PieceSpec] = {"front": front_spec, "back": back_spec}

    # ── Optional pieces ───────────────────────────────────────────────────────

    if closure_type in ("zip_fly", "button_fly"):
        fly_w = 5.0 if closure_type == "zip_fly" else 7.0
        _fly_note = (
            "fly facing strip; interface; sew to left front fly extension before inserting zip"
            if closure_type == "zip_fly" else
            "button fly facing strip; interface; sew to left front fly extension; make buttonholes before assembling"
        )
        pieces["fly_facing"] = _rect_piece("Fly Facing", fly_w, rise, 1, sa, notes=_fly_note)

    if has_fly_shield and closure_type == "zip_fly":
        pieces["fly_shield"] = _rect_piece("Fly Shield", 4.0, rise, 1, sa,
            notes="fly shield; interface; sits behind zip teeth on right front; attach at waistband")

    if has_front_pockets:
        bag_w = max(10.0, hip_qt * 0.60)
        pieces["pocket_bag"] = _rect_piece("Front Pocket Bag", bag_w, 16.0, 2, sa,
            notes="in-seam/side-slash pocket bag; insert into side seam before sewing Front Leg to Back Leg")

    if has_back_pockets:
        pieces["back_pocket"] = _rect_piece("Back Pocket", 14.0, 15.0, 2, sa,
            notes="back patch pocket; topstitch to Back Leg before assembling inseam and outseam")

    if has_cargo_pocket:
        pocket_w = max(14.0, hip_qt * 0.56)
        pieces["cargo_pocket"] = _rect_piece("Cargo Pocket", pocket_w, 22.0, 2, sa,
            notes="cargo pocket bag; topstitch to Front Leg outer thigh with bellows pleat before assembling legs")
        pieces["cargo_pocket_flap"] = _rect_piece("Cargo Pocket Flap", pocket_w, 6.5, 2, sa,
            notes="cargo pocket flap; interface; sew outer to lining RS together, turn and topstitch above cargo pocket opening")

    if has_cuff_band:
        band_w = ankle_half_f * 2 + sa * 2
        pieces["cuff_band"] = _rect_piece("Cuff Band", band_w, 12.0, 2, sa,
            notes="trouser turn-up cuff band; fold at hemline to form double-layer cuff; press and topstitch to secure")
    elif has_ankle_elastic:
        elastic_w = ankle_half_f * 2 * 0.80
        pieces["ankle_elastic"] = _rect_piece("Ankle Elastic Casing", elastic_w, 8.0, 2, sa,
            notes="ankle elastic casing strip; sew to trouser hem, fold over and stitch channel, thread elastic through")

    return pieces
