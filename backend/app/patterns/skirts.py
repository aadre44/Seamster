"""Straight skirt base block using the Aldrich parametric method.

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Each piece origin: center-front / center-back at x=0, waist at y=0
  - Hip line is at y = waist_to_hip_cm
  - Hem line is at y = length_cm
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.measurements import Measurements
from app.patterns.geometry import Point

EASE_CM = 2.0  # standard hip ease added to the full hip circumference


@dataclass
class DartSpec:
    """Single dart marking on a panel."""
    center_x: float       # x-coordinate of dart tip (on waist line)
    width: float          # dart width at waist (amount taken in)
    depth: float          # dart depth (length of dart legs from waist line)


@dataclass
class PieceSpec:
    """Geometric specification for one pattern piece (before .psnap serialisation)."""
    name: str
    outline: list[Point]           # closed polygon (CW in SVG coords)
    darts: list[DartSpec]
    grain_start: Point
    grain_end: Point
    cut_qty: int = 2
    on_fold: bool = False
    seam_allowance: float = 1.5    # cm; added by the engine when serialising


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


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

    # Dart intake: excess at waist compared to hip width
    # These are the amounts each half-panel must absorb via darts.
    dart_intake_f = hip_qt - w_qt_f   # positive = excess to take in
    dart_intake_b = hip_qt - w_qt_b

    # Dart depth (capped to keep dart within the wh region)
    dart_depth_f = _clamp(10.0, 6.0, wh * 0.75)
    dart_depth_b = _clamp(13.0, 8.0, wh * 0.90)

    # ── Front panel ───────────────────────────────────────────────────────────
    # Outline vertices (clockwise in SVG Y-down coords):
    #   CF-waist → SS-waist → SS-hip → SS-hem → CF-hem → back to CF-waist
    # Side seam is shaped: it angles outward from waist (w_qt_f) to hip (hip_qt).
    front_outline = [
        Point(0.0, 0.0),           # CF at waist (fold or seam)
        Point(w_qt_f, 0.0),        # SS at waist
        Point(hip_qt, wh),         # SS at hip (shaped outward)
        Point(hip_qt, L),          # SS at hem
        Point(0.0, L),             # CF at hem
    ]

    # 1 dart in front, placed at ~40 % of the waist-quarter width from CF
    front_dart_x = w_qt_f * 0.40
    front_dart_x = _clamp(front_dart_x, dart_intake_f / 2 + 0.5, w_qt_f - dart_intake_f / 2 - 0.5)
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
    )

    # ── Back panel ────────────────────────────────────────────────────────────
    back_outline = [
        Point(0.0, 0.0),           # CB at waist
        Point(w_qt_b, 0.0),        # SS at waist
        Point(hip_qt, wh),         # SS at hip
        Point(hip_qt, L),          # SS at hem
        Point(0.0, L),             # CB at hem
    ]

    # 2 darts in back, split evenly at 1/3 and 2/3 of the waist quarter
    dw_each = dart_intake_b / 2
    back_dart1_x = w_qt_b * 0.30
    back_dart1_x = _clamp(back_dart1_x, dw_each / 2 + 0.3, w_qt_b / 2 - dw_each / 2 - 0.3)
    back_dart2_x = w_qt_b * 0.65
    back_dart2_x = _clamp(back_dart2_x, w_qt_b / 2 + dw_each / 2 + 0.3, w_qt_b - dw_each / 2 - 0.3)

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
    )

    return {"front": front_spec, "back": back_spec}
