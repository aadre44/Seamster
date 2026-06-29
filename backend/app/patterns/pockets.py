"""Shared patch-pocket geometry for every garment block.

A patch pocket is applied flat to the outer fabric. Its opening (top edge) is
hemmed straight, but the *bottom* edge takes one of several common shapes. Real
garments show square, rounded, chamfered, pointed (chevron) and U-shaped bottoms
— a plain rectangle (the old default) misrepresents most of them.

`make_patch_pocket()` returns a `PieceSpec` whose outline starts at the top-left
corner and runs clockwise (top edge first, matching the engine serialiser's
fold-edge convention). The grain line runs vertically down the centre.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.patterns.geometry import CurveSegment, Point

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.patterns.skirts import PieceSpec

# Bezier "magic number" for a quarter-circle arc (also used in shirts.py).
_KAPPA = 0.5523

VALID_SHAPES = ("square", "rounded", "angled", "pointed", "curved")


def make_patch_pocket(
    name: str,
    width: float,
    height: float,
    sa: float,
    *,
    shape: str = "square",
    cut_qty: int = 1,
    corner: float = 2.5,
    notes: str = "",
) -> PieceSpec:
    """Build a patch pocket PieceSpec with the requested bottom shape.

    width / height : finished pocket dimensions (cm); height is the side-seam length.
    shape          : square | rounded | angled | pointed | curved
    corner         : corner radius (rounded) or chamfer size (angled), clamped to width/2.
    """
    # Deferred import keeps this module free of an import cycle with skirts.py
    # (skirts.py imports make_patch_pocket at module load).
    from app.patterns.skirts import PieceSpec

    shape = (shape or "square").lower()
    w, h = width, height
    c = max(0.0, min(corner, w / 2 - 0.1, h / 2 - 0.1))
    apex = max(2.0, w * 0.28)   # how far the pointed/curved bottom drops below h

    if shape == "pointed":
        # Chevron bottom meeting at a centre apex below the side corners.
        outline: list[Point | CurveSegment] = [
            Point(0.0, 0.0),
            Point(w, 0.0),
            Point(w, h),
            Point(w / 2, h + apex),
            Point(0.0, h),
        ]
    elif shape == "angled":
        # 45-degree chamfered bottom corners.
        outline = [
            Point(0.0, 0.0),
            Point(w, 0.0),
            Point(w, h - c),
            Point(w - c, h),
            Point(c, h),
            Point(0.0, h - c),
        ]
    elif shape == "rounded":
        # Straight bottom with quarter-circle corners of radius c.
        outline = [
            Point(0.0, 0.0),
            Point(w, 0.0),
            Point(w, h - c),
            CurveSegment(w - c, h, cp1=Point(w, h - c + c * _KAPPA), cp2=Point(w - c + c * _KAPPA, h)),
            Point(c, h),
            CurveSegment(0.0, h - c, cp1=Point(c - c * _KAPPA, h), cp2=Point(0.0, h - c + c * _KAPPA)),
        ]
    elif shape == "curved":
        # Single U-shaped bottom bowing down by ~apex.
        outline = [
            Point(0.0, 0.0),
            Point(w, 0.0),
            Point(w, h),
            CurveSegment(0.0, h, cp1=Point(w * 0.66, h + apex * 1.33), cp2=Point(w * 0.34, h + apex * 1.33)),
        ]
    else:  # square (default / unchanged)
        outline = [
            Point(0.0, 0.0),
            Point(w, 0.0),
            Point(w, h),
            Point(0.0, h),
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
        notes=notes or "patch pocket; press under seam allowances and topstitch to the garment front",
    )


def make_welt_pocket(
    width: float,
    sa: float,
    *,
    name_prefix: str = "Welt",
    welt_h: float = 2.5,
    bag_depth: float = 16.0,
    cut_qty: int = 1,
    besom: bool = False,
    placement_note: str = "",
) -> list[PieceSpec]:
    """Build the pieces for a bound welt (or double-besom) pocket.

    Returns ``[welt_strip, pocket_bag]``. Unlike the old hard-coded jacket welt, the
    opening ``width`` and welt height are parameters and ``placement_note`` records where
    the opening sits, so the same routine serves jackets, vests, trousers, etc.

    width        : finished welt opening width (cm).
    welt_h       : finished height of the welt lip(s) (cm); doubled for a besom (two lips).
    bag_depth    : pocket-bag depth below the opening (cm).
    cut_qty      : how many of this pocket appear (one strip + one bag per pocket).
    besom        : True → a double-besom (two narrow lips) instead of a single welt.
    """
    from app.patterns.skirts import PieceSpec

    w = max(4.0, width)
    strip_h = welt_h * 2.2 if besom else welt_h * 2.0  # folds to form the lip(s)
    kind = "double-besom" if besom else "single-welt"
    place = f" {placement_note}" if placement_note else ""

    strip = PieceSpec(
        name=f"{name_prefix} Strip",
        outline=[
            Point(0.0, 0.0), Point(w, 0.0),
            Point(w, strip_h), Point(0.0, strip_h),
        ],
        darts=[],
        grain_start=Point(w * 0.1, strip_h / 2),
        grain_end=Point(w * 0.9, strip_h / 2),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes=(
            f"{kind} welt strip for a bound pocket{place}; interface, fold to form the lip(s), and build "
            f"the welt opening on the garment before assembling the body"
        ),
    )
    bag = PieceSpec(
        name=f"{name_prefix} Pocket Bag",
        outline=[
            Point(0.0, 0.0), Point(w, 0.0),
            Point(w, bag_depth), Point(0.0, bag_depth),
        ],
        darts=[],
        grain_start=Point(w / 2, bag_depth * 0.15),
        grain_end=Point(w / 2, bag_depth * 0.85),
        cut_qty=cut_qty,
        on_fold=False,
        seam_allowance=sa,
        notes="welt pocket bag; sew to the welt strip and slip inside the opening; stitch the bag to "
              "the seam allowances only so it hangs behind the garment front",
    )
    return [strip, bag]
