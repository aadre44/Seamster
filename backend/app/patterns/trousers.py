"""Trouser / pants base block (Aldrich parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Origin: x=0 is the CF/CB crotch-seam edge; y=0 is the waist line
  - y increases toward ankle

Pieces produced: Front Leg, Back Leg, and conditionally: fly_facing, fly_shield,
pocket_bag, back_pocket, cargo_pocket, cargo_pocket_flap, cuff_band, ankle_elastic,
belt_loops.
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
from app.patterns.pockets import make_patch_pocket
from app.patterns.skirts import DartSpec, MarkSpec, PieceSpec, split_waist_reduction

# ── Fit-style parameter table ─────────────────────────────────────────────────
# hip_ease        : added to full hip before dividing by 4
# thigh_mult      : multiplier of hip_qt at crotch/thigh level
# ankle_mult_f/b  : multiplier of hip_qt (front) / hip_qt_b (back) at the ankle, so the
#                   leg opening scales with body size (a floor keeps it sewable on small
#                   frames). Earlier these were absolute cm — a fixed opening on every body.
# knee_nip        : cm the knee is pulled IN from the straight thigh→ankle line. 0 = a
#                   smooth side seam (tapered / straight / wide). A positive nip makes the
#                   leg slim at the knee and flare to the hem (flared / bootcut).
#                   NOTE: the knee is no longer an independent multiplier — it is
#                   interpolated between the thigh side-seam and the ankle (see _knee_half).
#                   The thigh is measured off the CF while the knee/ankle are off the grain
#                   centreline, so the old knee multiplier produced a jodhpur bulge.
# crotch_depth_f  : how far (cm) the front crotch arc dips below the rise line
# crotch_depth_b  : how far (cm) the back crotch arc dips below the rise line
#                   (deeper = more seat ease for sitting)
# back_tilt       : horizontal lean (cm) of the CB waist toward the side seam — the
#                   "seat angle" that leans the centre-back seam off vertical
# back_lift       : how far (cm) the CB waist corner rises above the side waist, so the
#                   centre-back seam is longer over the seat (room to sit/bend).
#                   Tighter/active fits tilt more; loose (palazzo/jogger) tilt less.
#                   Keep back_lift <= 2.0 so the corner stays near the layout origin.
_FIT_PARAMS: dict[str, dict] = {
    "skinny":    dict(hip_ease=-2.0, thigh_mult=0.90, knee_nip=0.0, ankle_mult_f=0.30, ankle_mult_b=0.33, crotch_depth_f=1.0, crotch_depth_b=2.0, back_tilt=2.5, back_lift=2.0),
    "slim":      dict(hip_ease=-1.0, thigh_mult=0.93, knee_nip=0.0, ankle_mult_f=0.39, ankle_mult_b=0.41, crotch_depth_f=1.2, crotch_depth_b=2.5, back_tilt=2.3, back_lift=1.8),
    "cigarette": dict(hip_ease=0.0,  thigh_mult=0.95, knee_nip=0.0, ankle_mult_f=0.40, ankle_mult_b=0.42, crotch_depth_f=1.2, crotch_depth_b=2.5, back_tilt=2.0, back_lift=1.5),
    "fitted":    dict(hip_ease=0.0,  thigh_mult=0.97, knee_nip=0.0, ankle_mult_f=0.43, ankle_mult_b=0.44, crotch_depth_f=1.3, crotch_depth_b=2.8, back_tilt=2.2, back_lift=1.8),
    "regular":   dict(hip_ease=2.0,  thigh_mult=1.00, knee_nip=0.0, ankle_mult_f=0.46, ankle_mult_b=0.48, crotch_depth_f=1.5, crotch_depth_b=3.0, back_tilt=2.0, back_lift=1.5),
    "relaxed":   dict(hip_ease=3.0,  thigh_mult=1.05, knee_nip=0.0, ankle_mult_f=0.50, ankle_mult_b=0.52, crotch_depth_f=1.8, crotch_depth_b=3.5, back_tilt=1.8, back_lift=1.2),
    "wide_leg":  dict(hip_ease=6.0,  thigh_mult=1.20, knee_nip=0.0, ankle_mult_f=1.10, ankle_mult_b=1.12, crotch_depth_f=2.0, crotch_depth_b=3.5, back_tilt=1.5, back_lift=1.0),
    "flared":    dict(hip_ease=2.0,  thigh_mult=0.95, knee_nip=6.0, ankle_mult_f=0.95, ankle_mult_b=0.97, crotch_depth_f=1.5, crotch_depth_b=3.0, back_tilt=2.0, back_lift=1.5),
    "bootcut":   dict(hip_ease=2.0,  thigh_mult=0.95, knee_nip=6.0, ankle_mult_f=0.92, ankle_mult_b=0.94, crotch_depth_f=1.5, crotch_depth_b=3.0, back_tilt=2.0, back_lift=1.5),
    "palazzo":   dict(hip_ease=8.0,  thigh_mult=1.35, knee_nip=0.0, ankle_mult_f=1.32, ankle_mult_b=1.34, crotch_depth_f=2.0, crotch_depth_b=4.0, back_tilt=1.2, back_lift=0.8),
    "jogger":    dict(hip_ease=3.0,  thigh_mult=1.05, knee_nip=0.0, ankle_mult_f=0.29, ankle_mult_b=0.31, crotch_depth_f=1.8, crotch_depth_b=4.0, back_tilt=1.5, back_lift=1.0),
}

# Minimum ankle half-widths (cm) so the leg opening clears the foot on small frames.
_ANKLE_FLOOR_F = 6.5
_ANKLE_FLOOR_B = 7.0
# Knee sits this fraction of the inseam below the crotch.
_KNEE_FRAC = 0.60
# Dart share / cap of each half-panel's hip→waist reduction (rest is side shaping).
TROUSER_DART_SPLIT_F = (0.35, 2.5)
TROUSER_DART_SPLIT_B = (0.6, 5.0)

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


def _rect_piece(name: str, w: float, h: float, cut_qty: int, sa: float, notes: str = "") -> PieceSpec:
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
        notes=notes,
    )


def _make_cargo_bellows_bag(
    W: float, H: float, depth: float, facing: float, corner: float, sa: float,
) -> PieceSpec:
    """A 3-D pleated-bellows cargo pocket bag.

    The flat piece is cut larger than the finished size so the bellows fold up to it:
    width = W + 4*depth (a side pleat each side, each consuming 2*depth), and
    height = facing + H + 2*depth (top turn-under + finished height + bottom pleat). The
    bottom corners are rounded so the folded-under allowance lies flat, and the side /
    bottom bellows fold + placement lines and the top facing fold are drawn as interior
    marks (the same MarkSpec mechanism the fly uses).
    """
    flat_w = W + 4 * depth
    flat_h = facing + H + 2 * depth
    bag = make_patch_pocket(
        "Cargo Pocket", flat_w, flat_h, sa, shape="rounded", cut_qty=2, corner=corner,
        notes=(
            f"pleated-bellows cargo pocket bag (finished ~{W:.0f}x{H:.0f} cm, {depth:.0f} cm depth); "
            "turn the top facing under and topstitch the opening, press the side + bottom bellows folds, "
            "then topstitch the bag to the Front Leg outer thigh leaving the top open; bartack the top corners"
        ),
    )
    y0, y1 = facing, flat_h - 2 * depth
    bag.marks = [
        MarkSpec(points=[Point(0.0, facing), Point(flat_w, facing)], label="pocket_facing_fold", dashed=True),
        # left bellows
        MarkSpec(points=[Point(2 * depth, y0), Point(2 * depth, y1)], label="bellows_fold", dashed=True),
        MarkSpec(points=[Point(depth, y0), Point(depth, y1)], label="bellows_placement"),
        # right bellows
        MarkSpec(points=[Point(flat_w - 2 * depth, y0), Point(flat_w - 2 * depth, y1)], label="bellows_fold", dashed=True),
        MarkSpec(points=[Point(flat_w - depth, y0), Point(flat_w - depth, y1)], label="bellows_placement"),
        # bottom bellows
        MarkSpec(points=[Point(2 * depth, flat_h - 2 * depth), Point(flat_w - 2 * depth, flat_h - 2 * depth)], label="bellows_fold", dashed=True),
        MarkSpec(points=[Point(2 * depth, flat_h - depth), Point(flat_w - 2 * depth, flat_h - depth)], label="bellows_placement"),
    ]
    return bag


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
    cargo_style: str = "bellows",       # bellows (pleated) | gusset | flat
    cargo_flap_shape: str = "square",   # square | rounded | angled | pointed | curved
    has_cuff_band: bool = False,
    has_ankle_elastic: bool = False,
    has_belt_loops: bool = False,       # emits a folded belt-loop strip piece
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

    # ── Dart suppression for elastic waist / jogger ───────────────────────────
    suppress_darts = closure_type == "elastic_waist"

    # Dart intakes: the hip→waist reduction is split between darts and the side
    # seam, and the waist edge carries the dart intake so the sewn waist is the
    # quarter (see split_waist_reduction). Trouser fronts take a small dart.
    if suppress_darts:
        dart_intake_f = dart_intake_b = 0.0
    else:
        dart_intake_f, _ = split_waist_reduction(hip_qt - waist_qt_f, *TROUSER_DART_SPLIT_F)
        dart_intake_b, _ = split_waist_reduction(hip_qt_b - waist_qt_b, *TROUSER_DART_SPLIT_B)
    waist_edge_f = waist_qt_f + dart_intake_f
    waist_edge_b = waist_qt_b + dart_intake_b

    # Thigh widths (at crotch level)
    thigh_half_f = hip_qt * fp["thigh_mult"]
    thigh_half_b = hip_qt_b * fp["thigh_mult"]

    # Grain centrelines (the leg "tube" below the crotch is symmetric about these)
    grain_x_f = (crotch_ext_f + hip_qt) / 2
    grain_x_b = (crotch_ext_b + hip_qt_b) / 2

    # Ankle widths — scale with body size (multiplier of the leg quarter), floored so
    # the opening still clears the foot on very small frames.
    ankle_half_f = max(_ANKLE_FLOOR_F, hip_qt * fp["ankle_mult_f"])
    ankle_half_b = max(_ANKLE_FLOOR_B, hip_qt_b * fp["ankle_mult_b"])

    # Knee (60% of the inseam below the crotch). The knee is INTERPOLATED between the
    # thigh side-seam and the ankle, not an independent multiplier — the thigh is measured
    # off the CF while the knee/ankle are off the grain centreline, so a raw knee
    # multiplier ballooned the leg out at the knee (jodhpur bulge). `knee_nip` pulls the
    # knee inward so flared/bootcut nip in at the knee and flare to the hem; 0 gives a
    # smooth tapered/straight/wide side seam.
    knee_y = rise + inseam * _KNEE_FRAC
    knee_nip = fp.get("knee_nip", 0.0)

    def _knee_half(thigh_ss_x: float, ankle_half: float, grain_x: float) -> float:
        ankle_ss_x = grain_x + ankle_half
        knee_ss_x = thigh_ss_x + _KNEE_FRAC * (ankle_ss_x - thigh_ss_x) - knee_nip
        return max(2.0, knee_ss_x - grain_x)

    knee_half_f = _knee_half(crotch_ext_f + thigh_half_f, ankle_half_f, grain_x_f)
    knee_half_b = _knee_half(crotch_ext_b + thigh_half_b, ankle_half_b, grain_x_b)

    # ── Crotch curve parameters ───────────────────────────────────────────────
    # Depth below the rise line (varies with fit — affects seating comfort and silhouette)
    crotch_depth_f = fp["crotch_depth_f"]
    crotch_depth_b = fp["crotch_depth_b"]

    # x-position of the inseam where it meets the start of the crotch arc.
    # For most fits this clamps to a small positive value; the arc then sweeps
    # rightward to crotch_ext where it meets the CF/CB edge.
    crotch_inseam_x_f = max(0.3, grain_x_f - thigh_half_f)
    crotch_inseam_x_b = max(0.3, grain_x_b - thigh_half_b)

    # ── Front Leg ─────────────────────────────────────────────────────────────
    # The crotch seam ([8]→[9]) is a cubic Bézier arc:
    #   [8] = deepest point of the crotch arc (at rise + depth below waist)
    #   [9] = CF at rise level (CurveSegment endpoint)
    #   cp1 sweeps the arc rightward from [8]; cp2 makes it arrive vertically at [9]
    front_outline: list[Point | CurveSegment] = [
        Point(crotch_ext_f, 0.0),                                # [0] CF at waist
        Point(crotch_ext_f + waist_edge_f, 0.0),                   # [1] SS at waist
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

    front_edge_labels = {
        0: "waist", 1: "side_seam", 2: "side_seam", 3: "side_seam", 4: "side_seam",
        5: "hem", 6: "inseam", 7: "inseam", 8: "crotch", 9: "center_front",
    }
    front_marks: list[MarkSpec] = []

    # ── Fly (straight CF + applied facing + shield model) ─────────────────────
    # The centre front is cut as a clean straight edge. A separate J-shaped Fly
    # Facing is applied to the LEFT front and a Fly Shield (underlap) backs the
    # RIGHT front — both emitted below. The only thing marked on the leg is the fly
    # topstitch "J", the line the finished fly is topstitched along (fly_ext in from
    # the CF, curving back to the CF at the bottom of the fly).
    has_fly = closure_type in ("zip_fly", "button_fly")
    if has_fly:
        fly_ext = 3.5 if closure_type == "zip_fly" else 4.0
        ts_x = crotch_ext_f + fly_ext
        front_marks.append(MarkSpec(
            points=[
                Point(ts_x, 0.0),
                CurveSegment(
                    x=crotch_ext_f, y=rise - 1.0,
                    cp1=Point(ts_x, rise - 1.0),
                    cp2=Point(ts_x - 0.5, rise - 0.5),
                ),
            ],
            label="fly_topstitch", dashed=False,
        ))

    front_darts: list[DartSpec] = []
    if not suppress_darts and dart_intake_f > 0.5:
        dart_x = _clamp(
            crotch_ext_f + waist_edge_f * 0.40,
            crotch_ext_f + dart_intake_f / 2 + 0.5,
            crotch_ext_f + waist_edge_f - dart_intake_f / 2 - 0.5,
        )
        front_darts.append(DartSpec(
            center_x=dart_x,
            width=dart_intake_f,
            depth=_clamp(9.0, 6.0, wh * 0.70),
        ))

    _front_dart_note = "" if suppress_darts else "; sew front waist dart(s) before attaching waistband"
    _front_fly_note = (
        "; CF is cut straight — apply the J-shaped Fly Facing to the left front and the "
        "Fly Shield to the right, then topstitch the fly along the marked J line"
        if has_fly else ""
    )
    front_spec = PieceSpec(
        name="Front Leg",
        outline=front_outline,
        darts=front_darts,
        grain_start=Point(grain_x_f, wh * 0.3),
        grain_end=Point(grain_x_f, total_length * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes=f"front trouser leg{_front_dart_note}{_front_fly_note}; inseam joins to Back Leg at crotch; outseam joins back at side seam",
        edge_labels=front_edge_labels,
        marks=front_marks,
    )

    # ── Back Leg ──────────────────────────────────────────────────────────────
    # Same curved crotch logic; back arc is deeper (more seat ease). In addition the
    # CB seam is *tilted for the seat*: the CB waist corner leans toward the side by
    # `back_tilt` and rises by `back_lift`, so the centre-back seam runs off-vertical
    # and is longer over the seat (room to sit/bend). The waist quarter is preserved by
    # shifting the side-seam waist corner out by the same `back_tilt`.
    back_tilt = fp["back_tilt"]
    back_lift = fp["back_lift"]
    cb_waist_x = crotch_ext_b + back_tilt
    cb_waist_pt = Point(cb_waist_x, -back_lift)               # raised, outset CB waist
    ss_waist_pt = Point(cb_waist_x + waist_edge_b, 0.0)       # side waist (quarter + dart intake)

    back_outline: list[Point | CurveSegment] = [
        cb_waist_pt,                                             # [0] CB at waist (tilted/lifted)
        ss_waist_pt,                                             # [1] SS at waist
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
        # Dart x measured from the tilted CB waist; legs ride the slanted waist edge.
        dart1_x = _clamp(
            cb_waist_x + waist_edge_b * 0.30,
            cb_waist_x + dw_each / 2 + 0.3,
            cb_waist_x + waist_edge_b / 2 - dw_each / 2 - 0.3,
        )
        dart2_x = _clamp(
            cb_waist_x + waist_edge_b * 0.65,
            cb_waist_x + waist_edge_b / 2 + dw_each / 2 + 0.3,
            cb_waist_x + waist_edge_b - dw_each / 2 - 0.3,
        )
        _back_baseline = (cb_waist_pt, ss_waist_pt)
        back_darts.append(DartSpec(center_x=dart1_x, width=dw_each, depth=dart_depth_b, baseline=_back_baseline))
        back_darts.append(DartSpec(center_x=dart2_x, width=dw_each, depth=dart_depth_b, baseline=_back_baseline))

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
        notes=f"back trouser leg with curved seat{_back_dart_note}; centre-back seam is tilted/raised for seat shaping (lengthen over the seat); deeper back rise; inseam joins Front Leg; outseam forms side seam",
        edge_labels={0: "waist", 1: "side_seam", 2: "side_seam", 3: "side_seam", 4: "side_seam", 5: "hem", 6: "inseam", 7: "inseam", 8: "crotch", 9: "center_back"},
    )

    pieces: dict[str, PieceSpec] = {"front": front_spec, "back": back_spec}

    # ── Optional pieces ───────────────────────────────────────────────────────

    if has_fly:
        # Applied-facing fly model: a J-shaped Fly Facing sewn to the (straight) CF of
        # the LEFT front, and a Fly Shield (underlap) backing the RIGHT front. The
        # facing's outer lower corner curves in toward the CF (the fly "J"), matching
        # the topstitch marked on the leg.
        fly_w = fly_ext + 3.0
        fly_h = rise
        facing_outline: list[Point | CurveSegment] = [
            Point(0.0, 0.0),                                  # CF/seam edge at waist
            Point(fly_w, 0.0),                                # outer edge at waist
            Point(fly_w, fly_h - fly_w),                      # outer edge, start of the J
            CurveSegment(                                     # sweep in to the CF at the bottom
                x=0.0, y=fly_h,
                cp1=Point(fly_w, fly_h),
                cp2=Point(fly_w * 0.4, fly_h),
            ),
        ]
        _facing_note = (
            "J-shaped fly facing; interface; sew to the LEFT front CF right-sides-together, "
            "turn and topstitch along the marked fly topstitch line before inserting the zip"
            if closure_type == "zip_fly" else
            "J-shaped button-fly facing; interface; make buttonholes; sew to the LEFT front CF, "
            "turn and topstitch along the marked fly line"
        )
        pieces["fly_facing"] = PieceSpec(
            name="Fly Facing",
            outline=facing_outline,
            darts=[],
            grain_start=Point(fly_w * 0.5, fly_h * 0.2),
            grain_end=Point(fly_w * 0.5, fly_h * 0.7),
            cut_qty=1,
            on_fold=False,
            seam_allowance=sa,
            notes=_facing_note,
        )
        # The shield is the standard partner to the applied facing — emit it for every
        # fly (the has_fly_shield flag can still force it on, but it is no longer needed).
        pieces["fly_shield"] = _rect_piece("Fly Shield", 4.0, fly_h, 1, sa,
            notes="fly shield / underlap; interface one half, fold lengthwise and finish the "
                  "curved inner edge; sits behind the fly on the RIGHT front, caught at the waistband")

    if has_front_pockets:
        bag_w = max(10.0, hip_qt * 0.60)
        pieces["pocket_bag"] = _rect_piece("Front Pocket Bag", bag_w, 16.0, 2, sa,
            notes="in-seam/side-slash pocket bag; insert into side seam before sewing Front Leg to Back Leg")

    if has_back_pockets:
        pieces["back_pocket"] = _rect_piece("Back Pocket", 14.0, 15.0, 2, sa,
            notes="back patch pocket; topstitch to Back Leg before assembling inseam and outseam")

    if has_cargo_pocket:
        pocket_w = max(14.0, hip_qt * 0.56)   # finished width
        pocket_h = 20.0                        # finished height
        cargo_depth = 4.0                      # bellows depth
        cargo_facing = 3.5                     # top turn-under
        cargo_corner = 1.5                     # rounded bottom corner

        if cargo_style == "flat":
            pieces["cargo_pocket"] = make_patch_pocket(
                "Cargo Pocket", pocket_w, pocket_h, sa, shape="square", cut_qty=2,
                notes="flat cargo patch pocket; press the seam allowances under and topstitch to the "
                      "Front Leg outer thigh, leaving the top open; bartack the top corners")
        elif cargo_style == "gusset":
            pieces["cargo_pocket"] = make_patch_pocket(
                "Cargo Pocket", pocket_w, pocket_h, sa, shape="rounded", cut_qty=2, corner=cargo_corner,
                notes="gusset cargo pocket bag; sew the gusset strip around the two sides and the bottom, "
                      "then topstitch to the Front Leg outer thigh leaving the top open")
            gusset_len = pocket_h * 2 + pocket_w   # side + bottom + side
            pieces["cargo_pocket_gusset"] = _rect_piece(
                "Cargo Pocket Gusset", gusset_len, cargo_depth + sa * 2, 2, sa,
                notes="cargo pocket gusset (depth band for the sides + bottom); ease/mitre around the two "
                      "bottom corners; gives the pocket its 3-D depth")
        else:  # bellows (pleated, default)
            pieces["cargo_pocket"] = _make_cargo_bellows_bag(
                pocket_w, pocket_h, cargo_depth, cargo_facing, cargo_corner, sa)

        flap_w = pocket_w + 1.5    # overhangs the opening slightly
        pieces["cargo_pocket_flap"] = make_patch_pocket(
            "Cargo Pocket Flap", flap_w, 6.5, sa, shape=cargo_flap_shape, cut_qty=2, corner=2.0,
            notes="cargo pocket flap; interface the outer; sew outer to facing RS together, turn and "
                  "topstitch; attach above the opening and close with a button / velcro")

        # Placement outline + bartack ticks on the Front Leg outer thigh.
        front_pocket = pieces["front"]
        px_right = crotch_ext_f + thigh_half_f - 2.0
        px_left = px_right - pocket_w
        py_top = rise + 5.0
        py_bot = py_top + pocket_h
        front_pocket.marks.append(MarkSpec(
            points=[Point(px_left, py_top), Point(px_right, py_top),
                    Point(px_right, py_bot), Point(px_left, py_bot), Point(px_left, py_top)],
            label="cargo_pocket_placement",
        ))
        front_pocket.marks.append(MarkSpec(
            points=[Point(px_left, py_top), Point(px_left + 1.2, py_top + 1.2)], label="bartack"))
        front_pocket.marks.append(MarkSpec(
            points=[Point(px_right, py_top), Point(px_right - 1.2, py_top + 1.2)], label="bartack"))

    if has_cuff_band:
        band_w = ankle_half_f * 2 + sa * 2
        pieces["cuff_band"] = _rect_piece("Cuff Band", band_w, 12.0, 2, sa,
            notes="trouser turn-up cuff band; fold at hemline to form double-layer cuff; press and topstitch to secure")
    elif has_ankle_elastic:
        elastic_w = ankle_half_f * 2 * 0.80
        pieces["ankle_elastic"] = _rect_piece("Ankle Elastic Casing", elastic_w, 8.0, 2, sa,
            notes="ankle elastic casing strip; sew to trouser hem, fold over and stitch channel, thread elastic through")

    if has_belt_loops:
        # Belt loops are cut as one strip, folded in thirds (finished ~1 cm wide).
        # Flat strip width = 3× finished width; height spans the waistband plus
        # bar-tack allowance at each end. Count scales with waist: 5 small, 7 larger.
        loop_count = 5 if W < 80.0 else 7
        loop_strip_w = 3.0 + sa * 2          # folded into a ~1 cm finished loop
        loop_strip_h = 8.0                   # waistband height + bar-tack allowance
        pieces["belt_loops"] = _rect_piece("Belt Loop", loop_strip_w, loop_strip_h, loop_count, sa,
            notes="belt loop strips; fold long edges to centre and topstitch, cut into "
                  f"{loop_count} loops, bar-tack evenly around the waistband")

    return pieces
