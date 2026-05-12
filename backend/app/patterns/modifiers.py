"""Silhouette and feature modifiers for the pattern engine.

Each modifier takes a dict of {name: PieceSpec} and returns a (possibly new)
dict of {name: PieceSpec} with the outline (and darts) adjusted for the
desired silhouette.
"""
from __future__ import annotations

import copy

from app.models.features import SkirtFeatures
from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.skirts import PieceSpec


def _adjust_hem(spec: PieceSpec, new_ss_hem_x: float) -> PieceSpec:
    """Return a copy of spec with the side-seam hem point shifted to new_ss_hem_x.

    Outline convention (from build_straight_skirt_block):
      index 0: CF/CB at waist
      index 1: SS at waist
      index 2: SS at hip
      index 3: SS at hem   ← we move this
      index 4: CF/CB at hem
    """
    s = copy.deepcopy(spec)
    s.outline[3] = Point(new_ss_hem_x, s.outline[3].y)
    return s


def apply_silhouette(
    base_pieces: dict[str, PieceSpec],
    features: SkirtFeatures,
    measurements: Measurements,
) -> dict[str, PieceSpec]:
    """Dispatch to the appropriate silhouette modifier and return updated pieces."""
    sil = features.silhouette

    if sil in ("straight", "gathered", "pleated"):
        # Gathered / pleated: the base block outline is straight — gathering/pleating
        # is a construction detail, not a shape change to the flat pattern pieces.
        return base_pieces

    if sil == "pencil":
        return _pencil(base_pieces, measurements)

    if sil == "a_line":
        return _a_line(base_pieces, measurements)

    if sil == "circle":
        return _circle(base_pieces, measurements)

    if sil == "wrap":
        return _wrap(base_pieces, measurements)

    return base_pieces


# ── Silhouette implementations ────────────────────────────────────────────────

def _pencil(pieces: dict[str, PieceSpec], m: Measurements) -> dict[str, PieceSpec]:
    """Pencil skirt: taper the hem to 90 % of hip width for a fitted silhouette."""
    hip_qt = (m.hip_cm + 2.0) / 4
    taper_factor = 0.90          # hem = 90 % of hip width → slight inward taper
    hem_x = hip_qt * taper_factor

    result: dict[str, PieceSpec] = {}
    for name, spec in pieces.items():
        result[name] = _adjust_hem(spec, hem_x)
    return result


def _a_line(pieces: dict[str, PieceSpec], m: Measurements) -> dict[str, PieceSpec]:
    """A-line skirt: flare the hem by adding ~5 cm per side seam quarter piece."""
    hip_qt = (m.hip_cm + 2.0) / 4
    flare_cm = 5.0               # cm added at each side seam hem point
    hem_x = hip_qt + flare_cm

    result: dict[str, PieceSpec] = {}
    for name, spec in pieces.items():
        result[name] = _adjust_hem(spec, hem_x)
    return result


def _circle(pieces: dict[str, PieceSpec], m: Measurements) -> dict[str, PieceSpec]:
    """Circle skirt: very wide flare — approximately 2× the straight hem width.

    A full-circle skirt is cut as a donut shape, but here we approximate it
    as a wide-flared panel (the user is expected to refine in the editor).
    """
    hip_qt = (m.hip_cm + 2.0) / 4
    hem_x = hip_qt * 2.0

    result: dict[str, PieceSpec] = {}
    for name, spec in pieces.items():
        result[name] = _adjust_hem(spec, hem_x)
    return result


def _wrap(pieces: dict[str, PieceSpec], m: Measurements) -> dict[str, PieceSpec]:
    """Wrap skirt: similar to a-line but with a wider waist opening.

    The front panel gets an extra 15 cm added horizontally (the wrap overlap).
    Back remains unchanged.
    """
    hip_qt = (m.hip_cm + 2.0) / 4
    flare_cm = 4.0
    hem_x = hip_qt + flare_cm

    result: dict[str, PieceSpec] = {}
    for name, spec in pieces.items():
        updated = _adjust_hem(spec, hem_x)
        if name == "front":
            # Extend the waist line by 15 cm for the wrap overlap
            o = updated.outline
            updated = copy.deepcopy(updated)
            updated.outline[1] = Point(o[1].x + 15.0, o[1].y)   # SS at waist
            updated.outline[2] = Point(o[2].x + 15.0, o[2].y)   # SS at hip
            updated.outline[3] = Point(o[3].x + 15.0, o[3].y)   # SS at hem
            updated.on_fold = False   # wrap front is not on fold
        result[name] = updated
    return result


def apply_feature_modifiers(
    pieces: dict[str, PieceSpec],
    features: SkirtFeatures,
    measurements: Measurements,
) -> dict[str, PieceSpec]:
    """Apply waistband, closure, and other feature-level adjustments."""
    result = pieces

    # Closure: if side_zip, add a small ease extension at side seam (already in hip ease)
    # If center_back_zip, the back pieces remain separate (already the default).
    # No geometric change needed for the base block — the editor handles placement.

    return result
