"""Orchestrates the full pattern generation pipeline."""
from app.models.features import SkirtFeatures
from app.models.measurements import Measurements
from app.patterns.geometry import Polygon
from app.patterns.skirts import build_straight_skirt_block
from app.patterns.modifiers import apply_silhouette, apply_feature_modifiers


def generate_pattern(features: SkirtFeatures, measurements: Measurements) -> dict[str, Polygon]:
    """Return all pattern pieces as named polygons (seam allowances included).

    Pipeline: base block → silhouette modifier → feature modifiers.
    Stub until Tasks 4–6 are complete.
    """
    base = build_straight_skirt_block(measurements)
    pieces = apply_silhouette(base, features, measurements)
    pieces = apply_feature_modifiers(pieces, features, measurements)
    return pieces
