"""Sleeveless vest base block.

A vest is a sleeveless upper-body garment: Front + Back bodice, never a sleeve. It reuses
the shirt boxy-bodice maths (fit parameters, armscye curve, quarter measurements) but adds
the features the reference garment needs and that no existing builder could express:

  - a **notched / split-V neckline** — a short narrow vertical slit at centre-front that
    flares into a V (with an optional notch step), drafted as real outline geometry rather
    than the single-point V the shirt block offers.
  - continuous **contrast edge binding** (neckline / armhole / hem) via ``finishings``.
  - shaped **armhole** and **hem facings** for a clean sleeveless finish.
  - placeable **welt pockets** on the lower front via ``pockets.make_welt_pocket``.

Coordinate system matches shirts.py: x=0 is the CF/CB fold, y=0 is the shoulder/nape level,
y grows toward the hem.
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.finishings import (
    make_armhole_facing,
    make_edge_binding,
    make_edge_facing,
    make_hem_facing,
    path_length,
)
from app.patterns.geometry import CurveSegment, Point
from app.patterns.pockets import make_welt_pocket
from app.patterns.shirts import EASE_CHEST, _DEFAULT_FIT, _FIT_PARAMS
from app.patterns.skirts import PieceSpec

# Necklines this block can draft natively (everything else falls back to the shirt-style V).
_VEST_NECKLINES = {"notched_v", "split_v", "v_neck"}

# Coarse per-silhouette contour baked at build time for the "fit_params" shape mode. Unlike the
# modifier/warp modes (which consume a fine-grained detected ShapeFeature), this is a fixed table
# keyed only on the fit style — the deliberately limited baseline to compare against.
#   hem_sweep   : cm added to the side-seam hem x (+ swing / − peg)
#   waist_taper : cm of side-seam suppression at the waist
#   hem_point   : cm the CF hem drops to a centre point (0 = straight)
_VEST_SHAPE_PARAMS: dict[str, dict[str, float]] = {
    "slim":      dict(hem_sweep=-2.0, waist_taper=2.5, hem_point=0.0),
    "fitted":    dict(hem_sweep=-1.0, waist_taper=2.0, hem_point=2.0),
    "regular":   dict(hem_sweep=0.0,  waist_taper=1.0, hem_point=0.0),
    "relaxed":   dict(hem_sweep=2.0,  waist_taper=0.0, hem_point=0.0),
    "boxy":      dict(hem_sweep=4.0,  waist_taper=0.0, hem_point=0.0),
    "oversized": dict(hem_sweep=6.0,  waist_taper=0.0, hem_point=0.0),
    "longline":  dict(hem_sweep=1.0,  waist_taper=0.5, hem_point=3.0),
}


_COLLAR_H = 4.0  # cm finished height of a mandarin / band stand collar


def _arm_curve(sh: Point, scye: Point) -> CurveSegment:
    """A sleeveless armscye curve from a shoulder tip to an armscye point (either side)."""
    return CurveSegment(
        scye.x, scye.y,
        cp1=Point(sh.x + (scye.x - sh.x) * 0.35, sh.y + (scye.y - sh.y) * 0.55),
        cp2=Point(scye.x, sh.y + (scye.y - sh.y) * 0.9),
    )


def _asymmetric_fronts(
    *,
    chest_qt: float,
    shoulder_tip_x: float,
    shoulder_slope: float,
    arm_depth: float,
    front_neck_w: float,
    L: float,
    sa: float,
    wrap_side: str,
    overlap_cm: float,
    closure_drop_frac: float,
) -> dict[str, PieceSpec]:
    """Draft an asymmetric wrap front as two DISTINCT non-mirrored panels.

    Drafted in a full-front frame: x = 0 is the left side seam, x = FW (= 2·chest_qt) the
    right side seam, centre front at x = cf. The Overlap (wrap) Front is the large panel whose
    free edge is a DIAGONAL closure running from the high-side neck down to the opposite lower
    front; the Underlap Front is the smaller panel that sits beneath it. ``wrap_side`` flips
    the whole construction by reflecting x → FW − x.
    """
    cf = chest_qt
    FW = 2 * chest_qt
    nw = front_neck_w
    neck_dip = 1.5
    underlap_ext = 4.0
    low_y = arm_depth + (L - arm_depth) * max(0.05, closure_drop_frac)

    # Overlap (wrap) panel — anchored high on the RIGHT (x > cf), diagonal down to the left.
    neck_hi = Point(cf + nw, neck_dip)
    sh_hi = Point(cf + shoulder_tip_x, shoulder_slope)
    scye_hi = Point(FW, arm_depth)
    hem_left = Point(max(0.0, cf - overlap_cm), L)
    diag_low = Point(max(0.0, cf - overlap_cm), low_y)
    overlap_outline: list[Point | CurveSegment] = [
        neck_hi,                       # 0 high neck (collar attaches)
        sh_hi,                         # 1 shoulder tip
        _arm_curve(sh_hi, scye_hi),    # 2 armscye (curve)
        Point(FW, L),                  # 3 right side hem
        hem_left,                      # 4 hem crosses to the left
    ]
    overlap_labels = {0: "shoulder", 1: "armhole", 2: "side_seam", 3: "hem"}
    if abs(diag_low.y - L) > 0.5:
        overlap_outline.append(diag_low)              # 5 up the short left edge
        overlap_labels[4] = "overlap_edge"
        overlap_labels[5] = "overlap_edge"            # diagonal closure → neck
    else:
        overlap_labels[4] = "overlap_edge"            # hem_left → neck (pure diagonal)

    # Underlap panel — the left half-front beneath the wrap.
    neck_lo = Point(cf - nw, neck_dip)
    sh_lo = Point(cf - shoulder_tip_x, shoulder_slope)
    scye_lo = Point(0.0, arm_depth)
    underlap_outline: list[Point | CurveSegment] = [
        neck_lo,                       # 0 left neck
        sh_lo,                         # 1 left shoulder tip
        _arm_curve(sh_lo, scye_lo),    # 2 left armscye (curve)
        Point(0.0, L),                 # 3 left side hem
        Point(cf + underlap_ext, L),   # 4 hem extends under the wrap
    ]
    underlap_labels = {0: "shoulder", 1: "armhole", 2: "side_seam", 3: "hem", 4: "underlap_edge"}

    if (wrap_side or "right").lower() == "left":
        def _reflect(v: Point | CurveSegment) -> Point | CurveSegment:
            if isinstance(v, CurveSegment):
                return CurveSegment(FW - v.x, v.y, Point(FW - v.cp1.x, v.cp1.y), Point(FW - v.cp2.x, v.cp2.y))
            return Point(FW - v.x, v.y)
        overlap_outline = [_reflect(v) for v in overlap_outline]
        underlap_outline = [_reflect(v) for v in underlap_outline]

    def _grain(outline: list[Point | CurveSegment]) -> tuple[Point, Point]:
        cx = sum(p.x for p in outline) / len(outline)
        return Point(cx, arm_depth), Point(cx, L * 0.85)

    og_s, og_e = _grain(overlap_outline)
    ug_s, ug_e = _grain(underlap_outline)
    overlap = PieceSpec(
        name="Overlap Front", outline=overlap_outline, darts=[],
        grain_start=og_s, grain_end=og_e, cut_qty=1, on_fold=False, seam_allowance=sa,
        notes="asymmetric WRAP front — the large outer panel; its diagonal free edge is the visible "
              "closure that crosses the body. Cut 1. Lays OVER the Underlap Front; fasten at the "
              "neck/upper edge; finish the diagonal edge (facing or binding).",
    )
    overlap.edge_labels = overlap_labels
    underlap = PieceSpec(
        name="Underlap Front", outline=underlap_outline, darts=[],
        grain_start=ug_s, grain_end=ug_e, cut_qty=1, on_fold=False, seam_allowance=sa,
        notes="asymmetric underlap front — the smaller inner panel that sits UNDER the wrap. Cut 1. "
              "Finish its inner edge; the Overlap Front laps over it.",
    )
    underlap.edge_labels = underlap_labels
    return {"overlap_front": overlap, "underlap_front": underlap}


def build_vest_block(
    m: Measurements,
    *,
    fit_style: str = "boxy",
    neckline: str = "notched_v",
    chest_ease_extra: float = 0.0,
    length_factor: float = 1.0,
    binding_edges: tuple[str, ...] = (),
    binding_width: float = 1.0,
    binding_contrast: bool = True,
    facings: tuple[str, ...] = (),
    welt_count: int = 0,
    welt_width: float = 14.0,
    welt_besom: bool = False,
    bake_shape: bool = False,
    front_style: str = "symmetric",
    wrap_side: str = "right",
    overlap_cm: float = 12.0,
    closure_drop_frac: float = 1.0,
    collar_style: str = "none",
) -> dict[str, PieceSpec]:
    """Return vest pattern pieces shaped by the analyzed garment features.

    fit_style       : controls bodice shape (slope, suppression, drop shoulder); boxy default.
    neckline        : notched_v | split_v | v_neck | (anything else → plain V).
    binding_edges   : which edges get a continuous binding strip — any of
                      "neckline", "armhole", "hem".
    binding_width   : finished visible binding width (cm).
    binding_contrast: cut the binding from contrast fabric.
    facings         : which edges get a turned facing piece — any of
                      "armhole", "hem", "neckline".
    welt_count      : number of lower-front welt pockets (0 = none).
    welt_width      : finished welt opening width (cm).
    welt_besom      : double-besom lips instead of a single welt.
    """
    chest = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    shoulder = m.shoulder_width_cm if m.shoulder_width_cm is not None else (chest / 4 + 7.5)
    W = m.waist_cm
    L = m.length_cm * length_factor
    sa = m.seam_allowance_cm

    fit_style = (fit_style or "boxy").lower()
    fp = _FIT_PARAMS.get(fit_style, _DEFAULT_FIT)
    shoulder_slope = fp["shoulder_slope"]
    armhole_extra = fp["armhole_extra"]
    waist_suppress = fp["waist_suppress"]
    drop_shoulder = fp["drop_shoulder"]

    total_ease = EASE_CHEST + chest_ease_extra
    chest_qt = (chest + total_ease) / 4
    shoulder_qt = shoulder / 2
    back_neck_w = chest / 10 + 1.0
    front_neck_w = back_neck_w
    arm_depth = chest / 4 + 4.0 + armhole_extra
    waist_y = arm_depth + 18.0
    waist_side = chest_qt - waist_suppress
    shoulder_tip_x = shoulder_qt + drop_shoulder

    neckline = (neckline or "notched_v").lower()

    # ── Armscye curve (shared by both bodices) ────────────────────────────────
    def _armscye() -> CurveSegment:
        return CurveSegment(
            x=chest_qt, y=arm_depth,
            cp1=Point(shoulder_tip_x - 0.4, shoulder_slope + (arm_depth - shoulder_slope) * 0.45),
            cp2=Point(chest_qt + 1.5, arm_depth - (arm_depth - shoulder_slope) * 0.12),
        )

    def _side_points(top_x: float) -> list[Point]:
        """Side-seam vertices from the armscye down to the CF/CB hem corner."""
        if waist_suppress == 0.0:
            return [Point(chest_qt, L)]
        return [Point(waist_side, waist_y), Point(W / 4 + 1.0, L)]

    # ── Notched / split-V neckline vertices (CF outward to the shoulder) ───────
    notch_depth = min(chest / 10 + 9.0, waist_y - 2.0)  # deepest point of the V at CF
    slit_w = 1.2          # half-width of the narrow CF slit
    slit_height = 4.0     # vertical run of the near-vertical slit before it flares
    slit_top_y = max(0.0, notch_depth - slit_height)

    A = Point(0.0, notch_depth)          # CF, bottom of the split (on the fold)
    B = Point(slit_w, slit_top_y)        # top of the narrow slit; A→B is the steep slit edge
    D = Point(front_neck_w, 0.0)         # shoulder-side neck point
    if neckline == "notched_v":
        notch_x = max(slit_w + 1.5, front_neck_w * 0.55)
        notch_y = slit_top_y * 0.45
        neck_pts: list[Point] = [A, B, Point(notch_x, notch_y), D]
    elif neckline in ("split_v", "v_neck"):
        neck_pts = [A, B, D] if neckline == "split_v" else [A, D]
    else:
        neck_pts = [A, D]

    # ── Front Bodice ──────────────────────────────────────────────────────────
    front_outline: list[Point | CurveSegment] = [
        *neck_pts,
        Point(shoulder_tip_x, shoulder_slope),
        _armscye(),
        *_side_points(chest_qt),
        Point(0.0, L),
    ]
    n = len(front_outline)
    neck_edges = len(neck_pts) - 1
    front_labels: dict[int, str] = {i: "neckline" for i in range(neck_edges)}
    front_labels[neck_edges] = "shoulder"
    front_labels[neck_edges + 1] = "armhole"
    for i in range(neck_edges + 2, n - 2):
        front_labels[i] = "side_seam"
    front_labels[n - 2] = "hem"
    front_labels[n - 1] = "center_front"

    _neck_desc = {
        "notched_v": "notched split-V neckline (a short narrow slit at CF that steps out through a "
                     "notch into a V)",
        "split_v": "split-V neckline (a short narrow slit at CF flaring into a clean V)",
        "v_neck": "V neckline",
    }.get(neckline, "V neckline")
    front_spec = PieceSpec(
        name="Front Bodice",
        outline=front_outline,
        darts=[],
        grain_start=Point(chest_qt / 2, arm_depth),
        grain_end=Point(chest_qt / 2, L * 0.85),
        cut_qty=2,
        on_fold=True,
        seam_allowance=sa,
        notes=f"vest front cut on the CF fold (one continuous panel — the {_neck_desc} is a shaped "
              f"edge, not an opening); sew to the Back at the shoulder seams then the side seams; "
              f"finish the neckline and sleeveless armholes",
    )
    front_spec.edge_labels = front_labels

    # ── Back Bodice ───────────────────────────────────────────────────────────
    back_outline: list[Point | CurveSegment] = [
        Point(0.0, 0.0),                 # CB nape
        Point(back_neck_w, 0.0),         # back-neck shoulder point
        Point(shoulder_tip_x, shoulder_slope),
        _armscye(),
        *_side_points(chest_qt),
        Point(0.0, L),
    ]
    bn = len(back_outline)
    back_labels: dict[int, str] = {0: "neckline", 1: "shoulder", 2: "armhole"}
    for i in range(3, bn - 2):
        back_labels[i] = "side_seam"
    back_labels[bn - 2] = "hem"
    back_labels[bn - 1] = "center_back"
    back_spec = PieceSpec(
        name="Back Bodice",
        outline=back_outline,
        darts=[],
        grain_start=Point(chest_qt / 2, arm_depth),
        grain_end=Point(chest_qt / 2, L * 0.85),
        cut_qty=2,
        on_fold=True,
        seam_allowance=sa,
        notes="vest back cut on the CB fold; shallow back neck; sew to the Front at the shoulder and "
              "side seams; finish the neckline and sleeveless armholes",
    )
    back_spec.edge_labels = back_labels

    pieces: dict[str, PieceSpec] = {"front_bodice": front_spec, "back_bodice": back_spec}

    # ── Asymmetric wrap front: replace the symmetric front with overlap + underlap panels ──
    if (front_style or "symmetric").lower() == "asymmetric_wrap":
        del pieces["front_bodice"]
        pieces.update(_asymmetric_fronts(
            chest_qt=chest_qt, shoulder_tip_x=shoulder_tip_x, shoulder_slope=shoulder_slope,
            arm_depth=arm_depth, front_neck_w=front_neck_w, L=L, sa=sa,
            wrap_side=wrap_side, overlap_cm=overlap_cm, closure_drop_frac=closure_drop_frac,
        ))

    # ── Mandarin / band stand collar ──────────────────────────────────────────
    if (collar_style or "none").lower() in ("mandarin", "band", "stand"):
        neck_circ = 2 * front_neck_w + 2 * back_neck_w
        pieces["collar"] = PieceSpec(
            name="Mandarin Collar",
            outline=[
                Point(0.0, 0.0), Point(neck_circ, 0.0),
                Point(neck_circ, _COLLAR_H), Point(0.0, _COLLAR_H),
            ],
            darts=[],
            grain_start=Point(neck_circ * 0.1, _COLLAR_H / 2),
            grain_end=Point(neck_circ * 0.9, _COLLAR_H / 2),
            cut_qty=2, on_fold=False, seam_allowance=sa,
            notes="mandarin / band stand collar; interface; sew short ends, attach the lower edge to "
                  "the neckline RS together, fold the inner layer under and topstitch; stands upright",
        )

    # ── fit_params shape mode: bake the coarse per-silhouette contour at build time ────
    if bake_shape:
        sp = _VEST_SHAPE_PARAMS.get(fit_style, _VEST_SHAPE_PARAMS["regular"])
        for spec in pieces.values():
            hem_idx = next((i for i, lbl in spec.edge_labels.items() if lbl == "hem"), None)
            if hem_idx is None or "Collar" in spec.name or "Binding" in spec.name or "Facing" in spec.name:
                continue
            o = spec.outline
            side = o[hem_idx]                      # side-seam hem corner
            cf = o[(hem_idx + 1) % len(o)]         # CF/CB hem corner (on the fold)
            o[hem_idx] = Point(max(0.0, side.x + sp["hem_sweep"]), side.y)
            if sp["hem_point"]:
                o[(hem_idx + 1) % len(o)] = Point(cf.x, cf.y + sp["hem_point"])

    # ── Edge subpaths reused by bindings + facings ────────────────────────────
    front_arm_pts: list[Point | CurveSegment] = [Point(shoulder_tip_x, shoulder_slope), _armscye()]
    back_arm_pts: list[Point | CurveSegment] = [Point(shoulder_tip_x, shoulder_slope), _armscye()]
    hem_pts: list[Point | CurveSegment] = [Point(0.0, L), Point(chest_qt, L)]

    # ── Continuous contrast binding(s) ────────────────────────────────────────
    binding_edges = tuple(e.lower() for e in binding_edges)
    if "neckline" in binding_edges:
        neck_len = 2 * path_length(neck_pts) + 2 * back_neck_w
        pieces["neck_binding"] = make_edge_binding(
            "Neckline Binding", neck_len, binding_width, sa,
            contrast=binding_contrast, cut_qty=1,
        )
    if "armhole" in binding_edges:
        arm_len = 2 * (path_length(front_arm_pts) + path_length(back_arm_pts))
        pieces["armhole_binding"] = make_edge_binding(
            "Armhole Binding", arm_len, binding_width, sa,
            contrast=binding_contrast, cut_qty=1,
        )
    if "hem" in binding_edges:
        hem_len = 2 * 2 * path_length(hem_pts)  # front + back, each cut on fold (×2)
        pieces["hem_binding"] = make_edge_binding(
            "Hem Binding", hem_len, binding_width, sa,
            contrast=binding_contrast, cut_qty=1,
        )

    # ── Facings ───────────────────────────────────────────────────────────────
    facings = tuple(f.lower() for f in facings)
    if "armhole" in facings:
        pieces["armhole_facing"] = make_armhole_facing(
            front_arm_pts, Point(0.0, arm_depth), sa, depth_cm=5.0, cut_qty=4,
        )
    if "hem" in facings:
        pieces["hem_facing"] = make_hem_facing(
            hem_pts, Point(chest_qt / 2, L - 14.0), sa, depth_cm=5.0, cut_qty=2,
        )
    if "neckline" in facings:
        pieces["neck_facing"] = make_edge_facing(
            "Neckline Facing", neck_pts, 4.0, Point(front_neck_w * 0.5, notch_depth * 0.5), sa,
            cut_qty=2,
            notes="neckline facing following the notched V; interface, finish the inner edge, sew RS "
                  "to the neckline, understitch and turn to the inside",
        )

    # ── Welt pockets (lower front) ────────────────────────────────────────────
    if welt_count > 0:
        welt = make_welt_pocket(
            welt_width, sa, name_prefix="Welt", welt_h=1.25, bag_depth=16.0,
            cut_qty=welt_count, besom=welt_besom,
            placement_note="on the lower front, mirrored either side of centre, ~3–4 cm above the hem",
        )
        pieces["welt_strip"], pieces["welt_pocket_bag"] = welt

    return pieces
