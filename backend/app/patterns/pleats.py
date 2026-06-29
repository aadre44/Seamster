"""Pleat geometry for the pattern engine.

A pleat is a fold of fabric. Accounting for a pleat on a *flat* pattern piece
means two things:

1. **Adding fabric width.** A folded pleat hides fabric, so the flat panel must
   be wider than the finished (worn) panel. The amount each pleat consumes:
       knife / accordion : 2 x depth   (one fold — fabric goes down `depth`, back up)
       box / inverted box: 4 x depth   (two mirrored folds)
       pintuck           : 2 x depth   (a tiny stitched knife pleat)
   `pleat_unit_allowance()` encodes this rule.

2. **Marking the fold.** Each pleat is drawn with a *fold line* (the crease that
   sits on top) and a *placement line* (where the fold is brought to), plus a
   direction. These are interior markings — not part of the cutting outline.

`build_pleats()` distributes N pleats across a region and reports the total
allowance. `apply_pleats()` widens a panel by that allowance and attaches the
marks, for localised waist pleats (trousers / dress / shirt back). Full-length
skirt pleats are built directly by the skirt block.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from app.patterns.skirts import PieceSpec


@dataclass
class PleatSpec:
    """One knife-fold pleat marking (interior fold + placement lines).

    A box / inverted-box pleat is represented as two mirrored PleatSpecs.
    """
    fold_x: float          # x of the fold line (crease that sits on top)
    placement_x: float     # x of the placement line (where the fold is brought to)
    y_top: float           # top of the marking (e.g. waist)
    y_bottom: float        # bottom of the marking (hem for full-length; release point otherwise)
    kind: str = "knife"    # knife | box | inverted_box | accordion | pintuck
    direction: str = "left"  # which way the fold faces (for the direction tick + notes)


_DOUBLE_FOLD_KINDS = {"box", "inverted_box"}


def pleat_unit_allowance(kind: str, depth: float) -> float:
    """Fabric width consumed by ONE pleat of the given finished depth (cm)."""
    kind = (kind or "knife").lower()
    if depth <= 0:
        return 0.0
    if kind in _DOUBLE_FOLD_KINDS:
        return 4.0 * depth   # two folds per box / inverted-box pleat
    return 2.0 * depth       # knife / accordion / pintuck: single fold


def build_pleats(
    x_start: float,
    x_end: float,
    y_top: float,
    y_bottom: float,
    *,
    count: int,
    depth: float,
    kind: str = "knife",
) -> tuple[list[PleatSpec], float]:
    """Evenly distribute ``count`` pleats across ``[x_start, x_end]``.

    The region passed in should already include the pleat allowance (i.e. it is
    the WIDENED fabric span), so the pleats are spaced across the real fabric.
    Returns ``(pleat_specs, total_allowance)``.
    """
    kind = (kind or "knife").lower()
    if count <= 0 or depth <= 0 or x_end <= x_start:
        return [], 0.0

    unit = pleat_unit_allowance(kind, depth)
    total = unit * count
    spacing = (x_end - x_start) / count

    specs: list[PleatSpec] = []
    for i in range(count):
        center = x_start + spacing * (i + 0.5)
        if kind == "box":
            # Two folds whose creases sit on top and face away from each other.
            specs.append(PleatSpec(center, center - depth, y_top, y_bottom, kind, "left"))
            specs.append(PleatSpec(center, center + depth, y_top, y_bottom, kind, "right"))
        elif kind == "inverted_box":
            # Two folds that meet (creases face toward the centre seam).
            specs.append(PleatSpec(center - depth, center, y_top, y_bottom, kind, "right"))
            specs.append(PleatSpec(center + depth, center, y_top, y_bottom, kind, "left"))
        else:
            # knife / accordion / pintuck: single fold facing one way.
            specs.append(PleatSpec(center + depth, center - depth, y_top, y_bottom, kind, "left"))
    return specs, total


def _shift_x(pt, insert_x: float, amount: float, max_y: float | None) -> None:
    """Translate a Point / CurveSegment rightward by ``amount`` if it sits beyond
    ``insert_x`` and (when ``max_y`` is set) at or above ``max_y`` in y.

    The ``max_y`` guard lets a waist pleat add fullness only near the waistline and
    taper out below (e.g. trouser pleats released at the hip), rather than widening
    the whole panel as a full-length skirt pleat does.
    """
    if max_y is not None and pt.y > max_y + 1e-9:
        return
    if pt.x > insert_x + 1e-9:
        pt.x += amount
        cp1 = getattr(pt, "cp1", None)
        cp2 = getattr(pt, "cp2", None)
        if cp1 is not None and cp1.x > insert_x + 1e-9:
            cp1.x += amount
        if cp2 is not None and cp2.x > insert_x + 1e-9:
            cp2.x += amount


def apply_pleats(
    spec: "PieceSpec",
    *,
    insert_x: float,
    count: int,
    depth: float,
    kind: str = "knife",
    y_top: float = 0.0,
    release_y: float | None = None,
    mark_region: tuple[float, float] | None = None,
    max_y: float | None = None,
) -> float:
    """Widen ``spec`` by the pleat allowance and attach the pleat markings.

    The panel is widened by inserting ``total`` cm of fabric at ``insert_x`` —
    every outline vertex to the right of ``insert_x`` shifts outward, so the side
    seam moves and the finished (folded) width returns to the original. Pass
    ``max_y`` to add the fullness only above that y (waist pleats tapering out by
    the hip); leave it None for a full-length skirt pleat.

    The pleats are marked from ``y_top`` down to ``release_y`` (or the panel hem
    when ``release_y`` is None). By default the marks are bunched in the inserted
    span ``[insert_x, insert_x + total]`` — pass ``mark_region=(x0, x1)`` (in the
    POST-widening coordinate system) to spread them across the whole panel
    instead, as for an all-over pleated skirt. Returns the total allowance added.
    """
    unit = pleat_unit_allowance(kind, depth)
    total = unit * count
    if total <= 0:
        return 0.0

    # 1. Insert the allowance: push everything beyond insert_x outward.
    for pt in spec.outline:
        _shift_x(pt, insert_x, total, max_y)
    if spec.grain_start.x > insert_x and (max_y is None or spec.grain_start.y <= max_y):
        spec.grain_start.x += total
    if spec.grain_end.x > insert_x and (max_y is None or spec.grain_end.y <= max_y):
        spec.grain_end.x += total
    for dart in spec.darts:
        if dart.center_x > insert_x:
            dart.center_x += total

    # 2. Mark the pleats.
    hem_y = max((p.y for p in spec.outline), default=y_top)
    y_bottom = release_y if release_y is not None else hem_y
    mx0, mx1 = mark_region if mark_region is not None else (insert_x, insert_x + total)
    pleats, _ = build_pleats(mx0, mx1, y_top, y_bottom, count=count, depth=depth, kind=kind)
    spec.pleats.extend(pleats)
    return total
