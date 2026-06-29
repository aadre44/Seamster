"""Reusable edge-finish pieces: continuous bindings and shaped facings.

The parametric builders historically modelled every "facing" as a plain rectangle and
had no concept of a *binding* at all. Real garments finish a neckline / armhole / hem in
one of two ways this module now generates as true pieces:

  - a **binding**: a narrow strip whose LENGTH equals the edge run-length; it is folded
    over the raw edge and topstitched, showing as a thin (optionally contrast) lip on the
    right side. ``make_edge_binding`` builds it from a known run-length.
  - a **facing**: a shaped band that FOLLOWS the edge (offset inward by a fixed depth) and
    turns fully to the inside. ``make_edge_facing`` (and the armhole/hem wrappers) build it
    from the edge's own outline points, so a curved armhole facing follows the curve rather
    than being flattened to a rectangle.

All functions return a ``PieceSpec`` (imported lazily to avoid an import cycle with
``skirts.py``). Coordinates are in cm, matching the rest of the engine.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.patterns.geometry import (
    CurveSegment,
    Point,
    cubic_bezier_points,
    polyline_length,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.patterns.skirts import PieceSpec


def _as_point(v: Point | CurveSegment) -> Point:
    return Point(v.x, v.y)


def _sample_path(points: list[Point | CurveSegment], steps: int = 16) -> list[Point]:
    """Flatten an outline subpath (Points + CurveSegments) into a dense polyline.

    A ``CurveSegment`` at index i means the edge arriving AT it from points[i-1] is a
    cubic Bézier; it is expanded into ``steps`` straight samples so lengths/offsets are
    accurate on curved edges (e.g. an armhole).
    """
    if not points:
        return []
    out: list[Point] = [_as_point(points[0])]
    for i in range(1, len(points)):
        cur = points[i]
        if isinstance(cur, CurveSegment):
            prev = _as_point(points[i - 1])
            samples = cubic_bezier_points(prev, cur.cp1, cur.cp2, Point(cur.x, cur.y), steps)
            out.extend(samples[1:])  # skip the duplicated start point
        else:
            out.append(_as_point(cur))
    return out


def path_length(points: list[Point | CurveSegment]) -> float:
    """Arc-length of an outline subpath, expanding any Bézier edges."""
    return polyline_length(_sample_path(points))


def make_edge_binding(
    name: str,
    run_length: float,
    width_cm: float,
    sa: float,
    *,
    contrast: bool = False,
    cut_qty: int = 1,
    notes: str = "",
) -> PieceSpec:
    """A continuous binding strip sized to a known edge run-length.

    The strip is cut LENGTH × HEIGHT where LENGTH = run_length (+ a little to turn the
    ends) and HEIGHT = enough to wrap the edge: 4 × finished width covers fold-over both
    sides plus seam allowance. Cut on the bias for a curved edge so it eases around it.
    """
    from app.patterns.skirts import PieceSpec

    length = run_length + 2.0          # a little extra to turn the short ends under
    height = max(2.0, width_cm * 4.0)  # wraps the raw edge: RS lip + turned-under WS lip + SA
    contrast_note = (
        "CUT FROM CONTRAST FABRIC — " if contrast else ""
    )
    outline = [
        Point(0.0, 0.0),
        Point(length, 0.0),
        Point(length, height),
        Point(0.0, height),
    ]
    return PieceSpec(
        name=name,
        outline=outline,
        darts=[],
        grain_start=Point(length * 0.1, height / 2),
        grain_end=Point(length * 0.9, height / 2),  # grain across the length = cut on the bias when laid 45°
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes=notes or (
            f"{contrast_note}continuous bias binding ~{width_cm:.1f} cm finished, cut on the bias so it "
            f"eases around curves; press in half lengthwise, sew RS to the raw edge, then wrap to the "
            f"inside and topstitch so a thin lip shows on the right side"
        ),
    )


def make_edge_facing(
    name: str,
    edge_points: list[Point | CurveSegment],
    depth_cm: float,
    interior_ref: Point,
    sa: float,
    *,
    cut_qty: int = 2,
    on_fold: bool = False,
    notes: str = "",
) -> PieceSpec:
    """A shaped facing band that follows ``edge_points`` offset inward by ``depth_cm``.

    The outer boundary is the edge itself; the inner boundary is each sampled edge point
    pushed ``depth_cm`` toward ``interior_ref`` (the garment interior), so the facing
    hugs a curved armhole/neckline instead of being a flat rectangle. The returned
    outline is a closed band (outer edge forward, inner edge back).
    """
    from app.patterns.skirts import PieceSpec

    outer = _sample_path(edge_points)
    if len(outer) < 2:
        raise ValueError("edge_points must describe at least a 2-point edge")

    inner: list[Point] = []
    for p in outer:
        to_interior = (interior_ref - p)
        d = to_interior.normalized()
        if d.x == 0.0 and d.y == 0.0:
            d = Point(0.0, 1.0)
        inner.append(Point(p.x + d.x * depth_cm, p.y + d.y * depth_cm))

    # Closed band: outer edge forward, then inner edge in reverse.
    outline: list[Point | CurveSegment] = [*outer, *reversed(inner)]

    xs = [p.x for p in outline]
    ys = [p.y for p in outline]
    cx = (min(xs) + max(xs)) / 2
    return PieceSpec(
        name=name,
        outline=outline,
        darts=[],
        grain_start=Point(cx, min(ys) + (max(ys) - min(ys)) * 0.2),
        grain_end=Point(cx, min(ys) + (max(ys) - min(ys)) * 0.8),
        cut_qty=cut_qty,
        on_fold=on_fold,
        seam_allowance=sa,
        notes=notes or (
            "shaped facing that follows the edge; interface, finish the inner edge, sew to the "
            "garment edge RS together, understitch and turn fully to the inside"
        ),
    )


def make_armhole_facing(
    armhole_points: list[Point | CurveSegment],
    interior_ref: Point,
    sa: float,
    *,
    depth_cm: float = 5.0,
    cut_qty: int = 4,
) -> PieceSpec:
    """Sleeveless armhole facing — follows the armscye curve, cut 4 (both armholes, 2 layers)."""
    return make_edge_facing(
        "Armhole Facing", armhole_points, depth_cm, interior_ref, sa,
        cut_qty=cut_qty,
        notes="sleeveless armhole facing; follows the armscye; interface, finish the inner edge, "
              "sew to the armhole RS together, understitch and turn to the inside",
    )


def make_hem_facing(
    hem_points: list[Point | CurveSegment],
    interior_ref: Point,
    sa: float,
    *,
    depth_cm: float = 5.0,
    cut_qty: int = 2,
) -> PieceSpec:
    """Hem facing band — follows the hem edge, offset up by depth, cut for front + back."""
    return make_edge_facing(
        "Hem Facing", hem_points, depth_cm, interior_ref, sa,
        cut_qty=cut_qty,
        notes="hem facing band following the hemline; interface, finish the upper edge, sew to the "
              "hem RS together, understitch and turn up to the inside",
    )
