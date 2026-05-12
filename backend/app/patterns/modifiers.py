"""Silhouette and feature modifiers for the pattern engine. Implemented in Tasks 5 & 6."""
from app.models.features import SkirtFeatures
from app.models.measurements import Measurements
from app.patterns.geometry import Polygon


def apply_silhouette(
    base_pieces: dict[str, Polygon],
    features: SkirtFeatures,
    measurements: Measurements,
) -> dict[str, Polygon]:
    """Dispatch to the appropriate silhouette modifier.
    Stub — full implementation in Task 5.
    """
    raise NotImplementedError("apply_silhouette not yet implemented (Task 5)")


def apply_feature_modifiers(
    pieces: dict[str, Polygon],
    features: SkirtFeatures,
    measurements: Measurements,
) -> dict[str, Polygon]:
    """Apply waistband, closure, darts, kick pleat, pockets, etc.
    Stub — full implementation in Task 6.
    """
    raise NotImplementedError("apply_feature_modifiers not yet implemented (Task 6)")
