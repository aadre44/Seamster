"""Skirt base block — parametric, supporting multiple silhouette styles.

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Each piece origin: center-front / center-back at x=0, waist at y=0
  - Hip line is at y = waist_to_hip_cm
  - Hem line is at y = length_cm (or _LENGTH_CM[length_category] when set)

Silhouettes:
  straight, pencil, a_line, flared, circle, gathered, pleated, wrap,
  trumpet, mermaid, tulip, tiered

Length categories:
  micro, mini, above_knee, knee, midi, maxi

Closure types:
  center_back_zip, side_zip, hook_and_eye, elastic

Optional detail pieces:
  pocket_bag, back_pocket, kick_pleat_facing, ruffle_tier
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.pleats import PleatSpec
from app.patterns.pockets import make_patch_pocket

EASE_CM = 2.0  # standard hip ease added to the full hip circumference

# ── Fit-style parameter table ──────────────────────────────────────────────────
# hem_mult      : multiplier of hip_qt for the side-seam hem x-coordinate
# suppress_darts: True → no sewn darts on flat pattern (gathered, pleated, circle, etc.)
# wrap_extra    : cm added to front SS waist / hip / hem x-coords (wrap overlap)
# knee_taper    : if not None, add a knee-level intermediate control point;
#                 value = knee_x / hip_qt ratio (< 1 = tapered at knee)
_FIT_PARAMS: dict[str, dict] = {
    "straight": dict(hem_mult=1.00, suppress_darts=False, wrap_extra=0.0,  knee_taper=None),
    "pencil":   dict(hem_mult=0.88, suppress_darts=False, wrap_extra=0.0,  knee_taper=None),
    "a_line":   dict(hem_mult=1.40, suppress_darts=False, wrap_extra=0.0,  knee_taper=None),
    "flared":   dict(hem_mult=1.80, suppress_darts=True,  wrap_extra=0.0,  knee_taper=None),
    "circle":   dict(hem_mult=2.20, suppress_darts=True,  wrap_extra=0.0,  knee_taper=None),
    "gathered": dict(hem_mult=1.20, suppress_darts=True,  wrap_extra=0.0,  knee_taper=None),
    "pleated":  dict(hem_mult=1.10, suppress_darts=True,  wrap_extra=0.0,  knee_taper=None),
    "wrap":     dict(hem_mult=1.10, suppress_darts=False, wrap_extra=15.0, knee_taper=None),
    "trumpet":  dict(hem_mult=1.60, suppress_darts=False, wrap_extra=0.0,  knee_taper=0.82),
    "mermaid":  dict(hem_mult=1.90, suppress_darts=False, wrap_extra=0.0,  knee_taper=0.78),
    "tulip":    dict(hem_mult=0.95, suppress_darts=False, wrap_extra=8.0,  knee_taper=None),
    "tiered":   dict(hem_mult=1.50, suppress_darts=True,  wrap_extra=0.0,  knee_taper=None),
}

# ── Length category → fixed hem length in cm (None = use measurement) ─────────
_LENGTH_CM: dict[str, float | None] = {
    "micro":      28.0,
    "mini":       42.0,
    "above_knee": 52.0,
    "knee":       60.0,
    "midi":       80.0,
    "maxi":       None,
}


@dataclass
class DartSpec:
    """Single dart marking on a panel."""
    center_x: float       # x-coordinate of dart tip (on waist line)
    width: float          # dart width at waist (amount taken in)
    depth: float          # dart depth (length of dart legs from waist line)
    # Optional slanted/raised waist baseline the dart sits on. When None the legs are
    # placed on y=0 (the default flat waistline). When set to a (left, right) waist
    # segment, each leg's y is interpolated along it and the tip is measured `depth`
    # below that — used by the tilted trouser back waist (seat tilt).
    baseline: tuple[Point, Point] | None = None


@dataclass
class MarkSpec:
    """Interior marking line/curve on a piece (not part of the sewn outline).

    Used for construction guides such as the fly fold/topstitch and the trouser
    pressed crease. Serialised as standalone interior elements that are excluded from
    the outline (so they never form seam connections). Default-empty on every piece, so
    garments that don't set it are unchanged.
    """
    points: list[Point | CurveSegment]   # polyline / bezier; CurveSegment = arc from prev point
    label: str = ""                       # seamLabel applied to the emitted elements
    dashed: bool = False                  # render as a fold line (dashed)


@dataclass
class PieceSpec:
    """Geometric specification for one pattern piece (before .psnap serialisation)."""
    name: str
    outline: list[Point | CurveSegment]  # closed polygon; CurveSegment = bezier from prev vertex
    darts: list[DartSpec]
    grain_start: Point
    grain_end: Point
    cut_qty: int = 2
    on_fold: bool = False
    seam_allowance: float = 1.5    # cm; added by the engine when serialising
    notes: str = ""                # construction context shown to the instruction generator
    edge_labels: dict[int, str] = field(default_factory=dict)  # edge index → seam name
    pleats: list[PleatSpec] = field(default_factory=list)      # interior pleat markings (fold + placement)
    marks: list[MarkSpec] = field(default_factory=list)        # interior construction marks (fly, crease)
    # Provenance: "engine" (parametric builder), "template" (learned store),
    # "llm" (fresh LLM piece / placeholder), or "vision" (photo contour).
    # Serialised onto the .psnap piece so the canvas can style AI drafts distinctly.
    source: str = "engine"
    detail: str = ""               # the detail token that produced a non-engine piece


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def split_waist_reduction(reduction: float, dart_share: float, dart_cap: float) -> tuple[float, float]:
    """Split a half-panel's hip→waist reduction between darts and side-seam shaping.

    Returns (dart_intake, side_shaping). The waist edge must be drawn at
    waist_quarter + dart_intake: sewing the darts then brings it to exactly the
    waist quarter, while the side seam curves in by side_shaping from the hip.
    (Drawing the edge at the waist quarter AND adding full-reduction darts takes
    the reduction twice — the sewn waist comes out far too small.)
    """
    if reduction <= 0:
        return 0.0, 0.0
    dart = min(reduction * dart_share, dart_cap)
    return dart, reduction - dart


# Aldrich-style split: one small front dart, two back darts taking more of the
# (larger) back reduction; the rest is side-seam shaping.
SKIRT_DART_SPLIT_F = (0.4, 3.0)
SKIRT_DART_SPLIT_B = (0.6, 6.0)


def build_straight_skirt_block(m: Measurements) -> dict[str, PieceSpec]:
    """Return front and back PieceSpecs for a straight skirt base block (Aldrich method).

    The outline is the finished-edge polygon (no seam allowance added yet).
    Darts are listed as interior markings — they are NOT part of the outline path.
    """
    W = m.waist_cm
    H = m.hip_cm
    wh = m.waist_to_hip_cm
    L = m.length_cm

    # Quarter measurements ─────────────────────────────────────────────────────
    hip_qt = (H + EASE_CM) / 4      # quarter hip with ease (panel width at hip level)
    w_qt_f = W / 4                  # quarter waist — front (no ease at waist)
    w_qt_b = W / 4                  # quarter waist — back

    # Aldrich uses a slight balance correction (+/- 0.5 cm front/back at waist):
    w_qt_f = W / 4 + 0.5           # front waist quarter (slightly wider)
    w_qt_b = W / 4 - 0.5           # back waist quarter (slightly narrower)

    # The hip→waist reduction is split between darts and side-seam shaping;
    # the waist edge carries the dart intake so the sewn waist is the quarter.
    dart_intake_f, _ = split_waist_reduction(hip_qt - w_qt_f, *SKIRT_DART_SPLIT_F)
    dart_intake_b, _ = split_waist_reduction(hip_qt - w_qt_b, *SKIRT_DART_SPLIT_B)
    edge_f = w_qt_f + dart_intake_f
    edge_b = w_qt_b + dart_intake_b

    # Dart depth (capped to keep dart within the wh region)
    dart_depth_f = _clamp(10.0, 6.0, wh * 0.75)
    dart_depth_b = _clamp(13.0, 8.0, wh * 0.90)

    # ── Front panel ───────────────────────────────────────────────────────────
    # Outline vertices (clockwise in SVG Y-down coords):
    #   CF-waist → SS-waist → SS-hip → SS-hem → CF-hem → back to CF-waist
    # Side seam is shaped: it angles outward from the waist edge to hip (hip_qt).
    front_outline = [
        Point(0.0, 0.0),           # CF at waist (fold or seam)
        Point(edge_f, 0.0),        # SS at waist
        Point(hip_qt, wh),         # SS at hip (shaped outward)
        Point(hip_qt, L),          # SS at hem
        Point(0.0, L),             # CF at hem
    ]

    # 1 dart in front, placed at ~40 % of the waist edge from CF
    front_dart_x = edge_f * 0.40
    front_dart_x = _clamp(front_dart_x, dart_intake_f / 2 + 0.5, edge_f - dart_intake_f / 2 - 0.5)
    front_darts = [DartSpec(
        center_x=front_dart_x,
        width=dart_intake_f,
        depth=dart_depth_f,
    )] if dart_intake_f > 0.1 else []

    front_grain_x = hip_qt / 2
    front_spec = PieceSpec(
        name="Front Skirt",
        outline=front_outline,
        darts=front_darts,
        grain_start=Point(front_grain_x, wh * 0.25),
        grain_end=Point(front_grain_x, L * 0.85),
        cut_qty=2,
        on_fold=True,              # center front on fold
        seam_allowance=m.seam_allowance_cm,
        edge_labels={0: "waist", 1: "side_seam", 2: "side_seam", 3: "hem", 4: "center_front"},
    )

    # ── Back panel ────────────────────────────────────────────────────────────
    back_outline = [
        Point(0.0, 0.0),           # CB at waist
        Point(edge_b, 0.0),        # SS at waist
        Point(hip_qt, wh),         # SS at hip
        Point(hip_qt, L),          # SS at hem
        Point(0.0, L),             # CB at hem
    ]

    # 2 darts in back, at roughly 1/3 and 2/3 of the waist edge
    dw_each = dart_intake_b / 2
    back_dart1_x = edge_b * 0.30
    back_dart1_x = _clamp(back_dart1_x, dw_each / 2 + 0.3, edge_b / 2 - dw_each / 2 - 0.3)
    back_dart2_x = edge_b * 0.65
    back_dart2_x = _clamp(back_dart2_x, edge_b / 2 + dw_each / 2 + 0.3, edge_b - dw_each / 2 - 0.3)

    back_darts = []
    if dart_intake_b > 0.1:
        back_darts.append(DartSpec(center_x=back_dart1_x, width=dw_each, depth=dart_depth_b))
        back_darts.append(DartSpec(center_x=back_dart2_x, width=dw_each, depth=dart_depth_b))

    back_grain_x = hip_qt / 2
    back_spec = PieceSpec(
        name="Back Skirt",
        outline=back_outline,
        darts=back_darts,
        grain_start=Point(back_grain_x, wh * 0.25),
        grain_end=Point(back_grain_x, L * 0.85),
        cut_qty=2,
        on_fold=False,             # CB is a seam (for closure)
        seam_allowance=m.seam_allowance_cm,
        edge_labels={0: "waist", 1: "side_seam", 2: "side_seam", 3: "hem", 4: "center_back"},
    )

    return {"front": front_spec, "back": back_spec}


# ── Shared geometry helpers ────────────────────────────────────────────────────

# Cubic Bézier constant for approximating a quarter-circle arc.
_BEZIER_K = 0.552


def _rect_piece(name: str, w: float, h: float, cut_qty: int, sa: float, notes: str = "") -> PieceSpec:
    """Return a simple rectangular PieceSpec with a vertical grain line."""
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
        grain_start=Point(w / 2, h * 0.1),
        grain_end=Point(w / 2, h * 0.9),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes=notes,
    )


def _patch_pocket_piece(
    name: str,
    w: float,
    h: float,
    cut_qty: int,
    sa: float,
    corner_r: float = 2.0,
    notes: str = "",
) -> PieceSpec:
    """Rectangular patch pocket with rounded lower corners.

    Standard sewing convention: patch pockets have curved lower corners so the
    seam allowance folds smoothly and the pocket lies flat on the garment.
    """
    k = _BEZIER_K
    r = min(corner_r, w / 2 - 0.1, h / 3)  # clamp to fit geometry
    outline: list[Point | CurveSegment] = [
        Point(0.0, 0.0),         # top-left
        Point(w, 0.0),           # top-right
        Point(w, h - r),         # right side, before bottom-right curve
        CurveSegment(            # bottom-right rounded corner (quarter-circle approx.)
            x=w - r, y=h,
            cp1=Point(w, h - r * (1 - k)),
            cp2=Point(w - r * (1 - k), h),
        ),
        Point(r, h),             # bottom, between the two corner curves
        CurveSegment(            # bottom-left rounded corner
            x=0.0, y=h - r,
            cp1=Point(r * (1 - k), h),
            cp2=Point(0.0, h - r * (1 - k)),
        ),
    ]
    return PieceSpec(
        name=name,
        outline=outline,
        darts=[],
        grain_start=Point(w / 2, h * 0.15),
        grain_end=Point(w / 2, h * 0.85),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes=notes,
    )


# ── Expanded skirt block ───────────────────────────────────────────────────────

def build_skirt_block(
    m: Measurements,
    fit_style: str = "straight",
    length_category: str = "maxi",
    closure_type: str = "center_back_zip",
    has_side_pockets: bool = False,
    has_patch_pockets: bool = False,
    has_patch_pocket_flap: bool = False,
    has_back_pockets: bool = False,
    has_kick_pleat: bool = False,
    has_side_slits: bool = False,
    has_ruffle_tier: bool = False,
    pocket_shape: str = "square",
) -> dict[str, PieceSpec]:
    """Return front / back panels plus conditional detail pieces.

    Silhouettes (fit_style):
        straight, pencil, a_line, flared, circle, gathered, pleated, wrap,
        trumpet, mermaid, tulip, tiered

    Length categories:
        micro, mini, above_knee, knee, midi, maxi  (None → use m.length_cm)

    Closure types:
        center_back_zip, side_zip, hook_and_eye, elastic
    """
    fp = _FIT_PARAMS.get(fit_style, _FIT_PARAMS["straight"])

    # ── Resolve measurements ──────────────────────────────────────────────────
    fixed_len = _LENGTH_CM.get(length_category)
    L = fixed_len if fixed_len is not None else m.length_cm
    L = max(L, m.waist_to_hip_cm + 5.0)   # hem must sit below the hip line

    W = m.waist_cm
    H = m.hip_cm
    wh = m.waist_to_hip_cm
    sa = m.seam_allowance_cm

    # ── Quarter measurements ──────────────────────────────────────────────────
    hip_qt = (H + EASE_CM) / 4
    w_qt_f = W / 4 + 0.5      # front (Aldrich balance correction)
    w_qt_b = W / 4 - 0.5      # back

    # ── Fit parameters ────────────────────────────────────────────────────────
    hem_mult   = fp["hem_mult"]
    hem_x      = hip_qt * hem_mult
    wrap_extra = fp["wrap_extra"]
    knee_taper = fp["knee_taper"]

    suppress_darts = fp["suppress_darts"]
    if closure_type == "elastic":
        suppress_darts = True

    # ── Dart intake ───────────────────────────────────────────────────────────
    # Darted skirts split the hip→waist reduction between darts and the side
    # seam; the waist edge carries the dart intake. Dartless silhouettes put it
    # all in the side seam.
    if suppress_darts:
        dart_intake_f = dart_intake_b = 0.0
    else:
        dart_intake_f, _ = split_waist_reduction(hip_qt - w_qt_f, *SKIRT_DART_SPLIT_F)
        dart_intake_b, _ = split_waist_reduction(hip_qt - w_qt_b, *SKIRT_DART_SPLIT_B)
    edge_f = w_qt_f + dart_intake_f
    edge_b = w_qt_b + dart_intake_b
    dart_depth_f  = _clamp(10.0, 6.0, wh * 0.75)
    dart_depth_b  = _clamp(13.0, 8.0, wh * 0.90)

    # ── Knee control point (trumpet / mermaid) ────────────────────────────────
    has_knee_point = knee_taper is not None
    knee_y = wh + (L - wh) * 0.65 if has_knee_point else None
    knee_x = hip_qt * knee_taper if has_knee_point else None

    # ── Curved side seam: SS-waist → SS-hip (smooth outward sweep) ───────────
    # cp1 is near the waist, cp2 near the hip; the curve gives a natural
    # S-shape that follows the body's silhouette from waist to hip.
    _ss_f_hip = CurveSegment(
        x=hip_qt + wrap_extra, y=wh,
        cp1=Point(edge_f + wrap_extra + (hip_qt - edge_f) * 0.12, wh * 0.30),
        cp2=Point(hip_qt + wrap_extra + 0.4, wh * 0.70),
    )
    _ss_b_hip = CurveSegment(
        x=hip_qt, y=wh,
        cp1=Point(edge_b + (hip_qt - edge_b) * 0.12, wh * 0.30),
        cp2=Point(hip_qt + 0.4, wh * 0.70),
    )

    # ── Front panel ───────────────────────────────────────────────────────────
    if has_knee_point:
        front_outline: list[Point | CurveSegment] = [
            Point(0.0, 0.0),
            Point(edge_f + wrap_extra, 0.0),
            _ss_f_hip,
            Point(knee_x, knee_y),
            Point(hem_x + wrap_extra, L),
            Point(0.0, L),
        ]
    else:
        front_outline = [
            Point(0.0, 0.0),
            Point(edge_f + wrap_extra, 0.0),
            _ss_f_hip,
            Point(hem_x + wrap_extra, L),
            Point(0.0, L),
        ]

    front_darts: list[DartSpec] = []
    if not suppress_darts and dart_intake_f > 0.1:
        dart_x = _clamp(
            edge_f * 0.40,
            dart_intake_f / 2 + 0.5,
            edge_f - dart_intake_f / 2 - 0.5,
        )
        front_darts.append(DartSpec(center_x=dart_x, width=dart_intake_f, depth=dart_depth_f))

    front_grain_x = hip_qt / 2
    front_on_fold = fit_style not in ("wrap", "tulip")
    _front_dart_note = "" if suppress_darts else "; sew waist dart(s) before attaching waistband"
    _fn = len(front_outline)
    front_spec = PieceSpec(
        name="Front Skirt",
        outline=front_outline,
        darts=front_darts,
        grain_start=Point(front_grain_x, wh * 0.25),
        grain_end=Point(front_grain_x, L * 0.85),
        cut_qty=2,
        on_fold=front_on_fold,
        seam_allowance=sa,
        notes=f"main front panel{_front_dart_note}; sew to Back Skirt at side seams",
        edge_labels={0: "waist", **{i: "side_seam" for i in range(1, _fn - 2)}, _fn - 2: "hem", _fn - 1: "center_front"},
    )

    # ── Back panel ────────────────────────────────────────────────────────────
    if has_knee_point:
        back_outline: list[Point | CurveSegment] = [
            Point(0.0, 0.0),
            Point(edge_b, 0.0),
            _ss_b_hip,
            Point(knee_x, knee_y),
            Point(hem_x, L),
            Point(0.0, L),
        ]
    else:
        back_outline = [
            Point(0.0, 0.0),
            Point(edge_b, 0.0),
            _ss_b_hip,
            Point(hem_x, L),
            Point(0.0, L),
        ]

    back_darts: list[DartSpec] = []
    if not suppress_darts and dart_intake_b > 0.1:
        dw_each = dart_intake_b / 2
        dart1_x = _clamp(edge_b * 0.30, dw_each / 2 + 0.3, edge_b / 2 - dw_each / 2 - 0.3)
        dart2_x = _clamp(edge_b * 0.65, edge_b / 2 + dw_each / 2 + 0.3, edge_b - dw_each / 2 - 0.3)
        back_darts.append(DartSpec(center_x=dart1_x, width=dw_each, depth=dart_depth_b))
        back_darts.append(DartSpec(center_x=dart2_x, width=dw_each, depth=dart_depth_b))

    back_grain_x = hip_qt / 2
    _back_dart_note = "" if suppress_darts else "; sew waist dart(s) before assembling"
    _closure_note = f"; {closure_type.replace('_', ' ')} at CB" if closure_type != "elastic" else "; elastic waist (no zip)"
    _bn = len(back_outline)
    back_spec = PieceSpec(
        name="Back Skirt",
        outline=back_outline,
        darts=back_darts,
        grain_start=Point(back_grain_x, wh * 0.25),
        grain_end=Point(back_grain_x, L * 0.85),
        cut_qty=2,
        on_fold=False,
        seam_allowance=sa,
        notes=f"main back panel{_back_dart_note}{_closure_note}; sew to Front Skirt at side seams",
        edge_labels={0: "waist", **{i: "side_seam" for i in range(1, _bn - 2)}, _bn - 2: "hem", _bn - 1: "center_back"},
    )

    pieces: dict[str, PieceSpec] = {"front": front_spec, "back": back_spec}

    # ── Optional detail pieces ────────────────────────────────────────────────
    if has_side_pockets:
        bag_w = max(10.0, hip_qt * 0.60)
        pieces["pocket_bag"] = _rect_piece("Side Pocket Bag", bag_w, 16.0, 2, sa,
            notes="in-seam pocket bag; insert into side seam before sewing Front Skirt to Back Skirt")

    if has_patch_pockets:
        pocket_w = max(12.0, hip_qt * 0.55)
        pocket_h = max(15.0, hip_qt * 0.80)
        # Skirt patch pockets default to softly rounded corners; honour a detected shape.
        shape = pocket_shape if pocket_shape in ("pointed", "angled", "curved", "rounded") else "rounded"
        pieces["patch_pocket"] = make_patch_pocket(
            "Front Patch Pocket", pocket_w, pocket_h, sa, shape=shape, cut_qty=2, corner=2.0,
            notes="applied patch pocket; press under seam allowances and topstitch to Front Skirt before assembling side seams",
        )
        if has_patch_pocket_flap:
            flap_h = max(6.0, pocket_w * 0.45)
            pieces["patch_pocket_flap"] = _patch_pocket_piece(
                "Patch Pocket Flap", pocket_w, flap_h, cut_qty=4, sa=sa, corner_r=1.5,
                notes="pocket flap (cut 4: 2 outer + 2 lining); sew outer to lining RS together, turn, topstitch above pocket opening",
            )

    if has_back_pockets:
        pieces["back_pocket"] = _rect_piece("Back Welt Pocket", 13.0, 14.0, 2, sa,
            notes="back welt pocket facing; construct welt opening on Back Skirt before assembling side seams")

    if has_kick_pleat:
        pieces["kick_pleat_facing"] = _rect_piece("Kick Pleat Facing", 15.0, 20.0, 1, sa,
            notes="kick pleat facing; interface; sew to back hem vent before stitching pleat closed")

    if has_ruffle_tier or fit_style == "tiered":
        tier_w = hip_qt * 2.0 * 1.5   # 150 % gather ratio
        tier_h = L * 0.30
        pieces["ruffle_tier"] = _rect_piece("Ruffle / Tier Strip", tier_w, tier_h, 2, sa,
            notes="ruffle/tier strip cut at 150% fullness; gather evenly before attaching to skirt hemline")

    return pieces
