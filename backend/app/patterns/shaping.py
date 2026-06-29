"""Garment-shape layer: reshape a built panel's CONTOUR (hem + side seam) after the block
is drafted, independent of garment type.

This finally wires up the post-build shape pipeline that ``modifiers.py`` only sketched
(`apply_silhouette` was imported and never called). It follows the in-place mutation pattern
established by ``pleats.py::apply_pleats`` — mutate ``outline`` / ``grain`` / ``edge_labels``
in place — and targets edges by their semantic ``seamLabel`` (``hem`` / ``side_seam`` /
``center_front``) so it works on any garment block.

Three interchangeable strategies (`shape_mode`) consume the SAME detected ``ShapeFeature``,
so they can be compared apples-to-apples:
  - "modifiers"  — composable named transforms (reshape_hem + apply_taper) [default].
  - "warp"       — remap the side+hem subpath onto a normalized control-point hull.
  - "fit_params" — baked into the builder; this layer is a no-op (handled in vests.py).
"""
from __future__ import annotations

from app.models.features import GarmentFeatures, ShapeFeature, ShapeMode, SilhouettePath
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.skirts import PieceSpec


# ── Edge / label helpers ──────────────────────────────────────────────────────

def _edge_index(spec: PieceSpec, label: str) -> int | None:
    """Index of the first outline edge carrying ``label`` (edge i = outline[i] → outline[i+1])."""
    for i, lbl in spec.edge_labels.items():
        if lbl == label:
            return i
    return None


def _has_label(spec: PieceSpec, label: str) -> bool:
    return label in spec.edge_labels.values()


def _max_x(spec: PieceSpec) -> float:
    return max(p.x for p in spec.outline)


def _max_y(spec: PieceSpec) -> float:
    return max(p.y for p in spec.outline)


def _waist_y(m: Measurements) -> float:
    chest = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    return chest / 4 + 4.0 + 18.0  # mirrors the bodice arm_depth + 18 convention


# ── Mode A: composable named modifiers ────────────────────────────────────────

def reshape_hem(spec: PieceSpec, style: str, depth: float, high_low: float = 0.0) -> None:
    """Replace the straight ``hem`` edge with a contoured one (in place).

    The hem edge runs from the side-seam hem corner (outline[k]) to the CF/CB hem corner
    (outline[k+1], on the fold). We mutate those two corners — and, for curved styles, turn
    the CF corner into a ``CurveSegment`` so the hem edge renders as a bezier. No vertices
    are inserted, so ``edge_labels`` stay valid.
    """
    style = (style or "straight").lower()
    if style == "straight":
        return
    k = _edge_index(spec, "hem")
    if k is None:
        return
    n = len(spec.outline)
    side = spec.outline[k]
    cf = spec.outline[(k + 1) % n]
    sx, sy, cx, cy = side.x, side.y, cf.x, cf.y

    if style == "pointed":
        # Drop the CF corner below the hemline → a centre point (mirrors to a V on the fold).
        spec.outline[(k + 1) % n] = Point(cx, cy + max(0.0, depth))
    elif style == "angled":
        # Raise the side corner → a straight diagonal hem slanting up toward the side seam.
        spec.outline[k] = Point(sx, sy - max(0.0, depth))
    elif style == "high_low":
        # CF and side hems at different heights (positive ⇒ CF shorter / higher).
        spec.outline[(k + 1) % n] = Point(cx, cy - high_low)
    elif style == "curved_scoop":
        # Smooth hem bowing down by ``depth`` at mid-panel.
        spec.outline[(k + 1) % n] = CurveSegment(
            cx, cy,
            cp1=Point(sx + (cx - sx) * 0.34, sy + depth),
            cp2=Point(sx + (cx - sx) * 0.66, cy + depth),
        )
    elif style == "cutaway":
        # Round the CF-hem corner away: raise the CF hem and sweep into it (open waistcoat front).
        spec.outline[(k + 1) % n] = CurveSegment(
            cx, cy - max(0.0, depth),
            cp1=Point(sx + (cx - sx) * 0.55, sy),
            cp2=Point(cx, cy - depth * 0.4),
        )


def apply_taper(spec: PieceSpec, waist_taper: float, hem_sweep: float, waist_y: float) -> None:
    """Shift the side-seam below the waist: suppress by ``waist_taper`` at the waist, sweep by
    ``hem_sweep`` at the hem (in place). + hem_sweep flares/swings; − pegs the hem.

    Side vertices are the ones in the outer x-column at or below the waist anchor; each is
    offset along x by a value ramped from −waist_taper at the waist to +hem_sweep at the hem.
    """
    if waist_taper == 0.0 and hem_sweep == 0.0:
        return
    L = _max_y(spec)
    mx = _max_x(spec)
    span = max(1e-6, L - waist_y)
    for i, p in enumerate(spec.outline):
        if p.x <= mx * 0.5 or p.y < waist_y - 1e-6:
            continue  # not a lower side-seam vertex
        t = min(1.0, max(0.0, (p.y - waist_y) / span))
        dx = -waist_taper * (1.0 - t) + hem_sweep * t
        p.x = max(0.0, p.x + dx)
        if isinstance(p, CurveSegment):
            p.cp1.x = max(0.0, p.cp1.x + dx)
            p.cp2.x = max(0.0, p.cp2.x + dx)


def reshape_side_vent(spec: PieceSpec, height: float) -> None:
    """Open the lower side seam into a vent ``height`` cm above the hem (in place).

    Splits the side-seam edge adjacent to the hem: the upper part stays ``side_seam`` (sewn
    front↔back), the lower part is relabelled to an empty (unconnected) edge so it reads as
    an OPEN vent finished on each panel separately. A vertex is inserted, so following edge
    labels are re-indexed. Applies to both front and back (any panel with side_seam + hem).
    """
    if height <= 0:
        return
    k = _edge_index(spec, "hem")
    if k is None:
        return
    n = len(spec.outline)
    ss_idx = (k - 1) % n  # the side-seam edge ending at the hem side corner: outline[k-1] → outline[k]
    if spec.edge_labels.get(ss_idx) != "side_seam":
        return  # unexpected layout — skip safely
    upper = spec.outline[ss_idx]
    lower = spec.outline[k]                 # hem side corner
    seam_len = lower.y - upper.y
    if seam_len <= 1e-6:
        return
    height = min(height, seam_len * 0.6)    # a vent can't consume the whole seam
    t = (lower.y - height - upper.y) / seam_len
    vent = Point(upper.x + t * (lower.x - upper.x), lower.y - height)

    spec.outline = spec.outline[:k] + [vent] + spec.outline[k:]
    new_labels: dict[int, str] = {}
    for i, lbl in spec.edge_labels.items():
        new_labels[i if i < k else i + 1] = lbl
    new_labels[k] = ""  # vent → hem corner: open, finished separately (never auto-connected)
    spec.edge_labels = new_labels
    spec.notes = (spec.notes or "") + (
        f"; leave the side seam open {height:.0f} cm above the hem for a side vent — "
        f"finish each edge separately and bar-tack the vent top"
    )


def apply_front_cut(spec: PieceSpec, style: str, depth: float) -> None:
    """Open / cut away the lower centre-front of the FRONT panel (in place).

    Below a break point the centre-front sweeps outward by ``depth`` so the two fronts no
    longer meet at the hem (a waistcoat cutaway / open-drape front). Turns the front off the
    fold (cut 2, real CF edge). Only acts on a front panel (has center_front, not center_back);
    a wrap/surplice overlap is NOT a cut and stays ``closed``.
    """
    style = (style or "closed").lower()
    if style == "closed" or depth <= 0:
        return
    if not (_has_label(spec, "center_front") and not _has_label(spec, "center_back")):
        return
    c = _edge_index(spec, "center_front")
    if c is None:
        return
    n = len(spec.outline)
    cf_hem = spec.outline[c]              # CF hem corner (on the fold, x≈0)
    A = spec.outline[(c + 1) % n]         # top of the CF edge (neckline bottom)
    L = _max_y(spec)
    top_y = A.y
    break_frac = 0.35 if style == "cutaway" else 0.15  # open_drape breaks higher up
    break_y = top_y + (L - top_y) * break_frac

    spec.outline[c] = Point(depth, L)     # CF hem corner swings out → the open gap
    # Break vertex on the fold line, reached by a curve so cf_hem'→B reads as a cutaway sweep.
    brk = CurveSegment(
        0.0, break_y,
        cp1=Point(depth * 0.9, L - (L - break_y) * 0.30),
        cp2=Point(depth * 0.45, break_y + (L - break_y) * 0.20),
    )
    spec.outline = spec.outline[: c + 1] + [brk] + spec.outline[c + 1:]
    new_labels: dict[int, str] = {}
    for i, lbl in spec.edge_labels.items():
        new_labels[i if i <= c else i + 1] = lbl
    new_labels[c] = "center_front"        # cf_hem' → break (the cutaway curve)
    new_labels[c + 1] = "center_front"    # break → neckline (upper CF seam)
    spec.edge_labels = new_labels
    spec.on_fold = False
    spec.cut_qty = 2
    spec.notes = (spec.notes or "") + (
        f"; lower centre-front {style.replace('_', ' ')} — cut 2 (off the fold); the fronts open "
        f"~{depth:.0f} cm at the hem below the closure; face/finish the centre-front edges"
    )


# ── Mode B: control-point warp ────────────────────────────────────────────────

def _synthesize_path(shape: ShapeFeature | None, mx: float, y0: float, L: float) -> list[tuple[float, float]]:
    """Build a normalized side+hem hull from a ShapeFeature so the warp mode always has input.

    x: 0 = CF/CB fold, 1 = side seam (may exceed 1 for flare). y: 0 = underarm anchor, 1 = hem.
    """
    shape = shape or ShapeFeature()
    span_y = max(1e-6, L - y0)
    sweep_n = (shape.hem_sweep_cm / mx) if mx else 0.0
    depth_n = shape.hem_depth_cm / span_y
    hl_n = shape.high_low_cm / span_y

    pts: list[tuple[float, float]] = [(1.0, 0.0), (1.0 + sweep_n, 1.0)]  # side top → side hem
    style = shape.hem_style
    if style == "pointed":
        pts.append((0.0, 1.0 + depth_n))
    elif style == "curved_scoop":
        pts.append((0.5, 1.0 + depth_n))
        pts.append((0.0, 1.0))
    elif style == "high_low":
        pts.append((0.0, 1.0 - hl_n))
    elif style == "cutaway":
        pts.append((0.25, 1.0))
        pts.append((0.0, 1.0 - depth_n))
    else:  # straight / angled
        pts.append((0.0, 1.0))
    return pts


def warp_to_silhouette(spec: PieceSpec, norm_pts: list[tuple[float, float]]) -> None:
    """Remap the side+hem subpath (underarm anchor → CF hem) onto a normalized hull (in place).

    The neckline / shoulder / armhole and the CF fold are anchored; only the lower contour is
    rebuilt from ``norm_pts`` scaled to the panel bbox. x is clamped ≥ 0 so the outline stays
    simple and the CF fold edge is preserved.
    """
    a = _edge_index(spec, "armhole")
    if a is None or not norm_pts:
        return
    anchor_idx = a + 1                      # the armscye/underarm vertex
    if anchor_idx >= len(spec.outline):
        return
    anchor = spec.outline[anchor_idx]
    y0 = anchor.y
    L = _max_y(spec)
    mx = _max_x(spec)
    span_y = max(1e-6, L - y0)

    mapped: list[Point] = []
    for nx, ny in norm_pts:
        x = max(0.0, nx * mx)
        y = y0 + ny * span_y
        mapped.append(Point(x, y))
    # Drop a leading point coincident with the anchor to avoid a zero-length edge.
    if mapped and abs(mapped[0].x - anchor.x) < 0.5 and abs(mapped[0].y - anchor.y) < 0.5:
        mapped = mapped[1:]
    # Guarantee the contour closes back at the CF/CB fold (x ≈ 0) at hem level.
    if not mapped or abs(mapped[-1].x) > 0.1:
        mapped.append(Point(0.0, L))

    head = spec.outline[: anchor_idx + 1]
    new_outline: list[Point | CurveSegment] = [*head, *mapped]
    spec.outline = new_outline

    # Rebuild labels: keep the head edges (neckline/shoulder/armhole), the new lower contour is
    # side_seam, the final segment into the fold is hem, the closing edge is the CF/CB fold.
    n = len(new_outline)
    labels: dict[int, str] = {i: spec.edge_labels.get(i, "") for i in range(anchor_idx)}
    for i in range(anchor_idx, n - 2):
        labels[i] = "side_seam"
    labels[n - 2] = "hem"
    labels[n - 1] = "center_back" if _has_label(spec, "center_back") else "center_front"
    spec.edge_labels = labels


# ── Dispatcher ────────────────────────────────────────────────────────────────

def apply_shape(
    pieces: dict[str, PieceSpec],
    features: GarmentFeatures,
    measurements: Measurements,
    mode: ShapeMode = "modifiers",
) -> dict[str, PieceSpec]:
    """Apply the selected shape strategy to the main bodice panels (in place) and return them.

    Only panels with both an ``armhole`` and a ``hem`` (the body front/back) are warped;
    only panels with a ``hem`` are reshaped — trim pieces (bindings/facings/welts) are skipped.
    ``fit_params`` is a no-op here (the builder baked the shape).
    """
    if mode == "fit_params":
        return pieces

    shape = features.shape
    waist_y = _waist_y(measurements)

    if mode == "modifiers":
        if shape is None:
            return pieces
        for spec in pieces.values():
            if _has_label(spec, "hem"):
                reshape_hem(spec, shape.hem_style, shape.hem_depth_cm, shape.high_low_cm)
                apply_taper(spec, shape.waist_taper_cm, shape.hem_sweep_cm, waist_y)
                reshape_side_vent(spec, shape.side_vent_cm)
            apply_front_cut(spec, shape.front_cut, shape.front_cut_depth_cm)
        return pieces

    if mode == "warp":
        path: SilhouettePath | None = features.silhouette_path
        for name, spec in pieces.items():
            if not (_has_label(spec, "armhole") and _has_label(spec, "hem")):
                continue
            # Per-panel hull (asymmetric garments supply a distinct outline per piece) takes
            # precedence; otherwise fall back to the shared front/back hull or a synthesized one.
            per_panel = path.panels.get(name) if path is not None and path.panels else None
            is_back = _has_label(spec, "center_back")
            shared = (path.back if is_back else path.front) if path is not None else []
            pts = per_panel or shared or _synthesize_path(
                shape, _max_x(spec), _waist_y(measurements), _max_y(spec)
            )
            warp_to_silhouette(spec, pts)
        return pieces

    return pieces
