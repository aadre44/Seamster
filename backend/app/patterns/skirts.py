"""Straight skirt base block (Aldrich method). Implemented in Task 4."""
from app.models.measurements import Measurements
from app.patterns.geometry import Point, Polygon

EASE_CM = 2.0  # standard ease added to hip measurement


def build_straight_skirt_block(m: Measurements) -> dict[str, Polygon]:
    """Return {'front': [...], 'back': [...]} polygons for the base straight skirt.
    Stub — full implementation in Task 4.
    """
    raise NotImplementedError("build_straight_skirt_block not yet implemented (Task 4)")
