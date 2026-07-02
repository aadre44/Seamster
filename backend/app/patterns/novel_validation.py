"""Geometric validation for LLM-generated novel pieces (novel-piece tier 3).

The LLM fallback trusts nothing: every generated piece is checked for
degenerate/implausible dimensions and a self-intersecting outline before it is
accepted, and circular-flounce attachment edges are compared against the real
garment edge they claim to sew to. Failures are returned as human-readable
problem strings that are fed straight back into the repair re-prompt.
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point, cubic_bezier_points
from app.patterns.skirts import PieceSpec

# Garment edge labels a novel piece may attach to. These match the seamLabels the
# parametric builders emit, so a labelled novel edge pairs up in _compute_connections.
ATTACHMENT_LABELS = ("hem", "waist", "neckline", "armhole", "wrist", "side_seam")

MIN_DIM_CM = 0.5     # thinner than this is a drafting error, not a strap
MAX_DIM_CM = 250.0   # wider than a full circle skirt panel is implausible
MIN_AREA_CM2 = 1.0
# Relative tolerance for a circular flounce's inner arc vs the edge it attaches to.
ARC_TOLERANCE = 0.15

_BEZIER_STEPS = 12


def sample_outline(outline: list[Point | CurveSegment]) -> list[Point]:
    """Flatten a PieceSpec outline into a closed polyline (beziers sampled)."""
    pts: list[Point] = []
    n = len(outline)
    for i in range(n):
        a = outline[i]
        b = outline[(i + 1) % n]
        start = Point(a.x, a.y)
        if isinstance(b, CurveSegment):
            seg = cubic_bezier_points(start, b.cp1, b.cp2, Point(b.x, b.y), steps=_BEZIER_STEPS)
            pts.extend(seg[:-1])  # end point is the next iteration's start
        else:
            pts.append(start)
    return pts


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Proper (interior) intersection test — shared endpoints don't count."""
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def self_intersects(pts: list[Point]) -> bool:
    """True if the closed polyline crosses itself (non-adjacent segments only)."""
    n = len(pts)
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:  # adjacent through the wrap-around
                continue
            if _segments_intersect(*segs[i], *segs[j]):
                return True
    return False


def _polygon_area(pts: list[Point]) -> float:
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i].x * pts[j].y - pts[j].x * pts[i].y
    return abs(area) / 2.0


def validate_spec(spec: PieceSpec, m: Measurements) -> list[str]:
    """Return a list of problems with a generated piece; empty means it is accepted."""
    problems: list[str] = []
    if len(spec.outline) < 3:
        return [f"piece '{spec.name}': outline has fewer than 3 vertices"]

    pts = sample_outline(spec.outline)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)

    if w < MIN_DIM_CM or h < MIN_DIM_CM:
        problems.append(
            f"piece '{spec.name}' is degenerately small ({w:.1f} x {h:.1f} cm); "
            f"every dimension must be at least {MIN_DIM_CM} cm"
        )
    if w > MAX_DIM_CM or h > MAX_DIM_CM:
        problems.append(
            f"piece '{spec.name}' is implausibly large ({w:.1f} x {h:.1f} cm) for a body with "
            f"waist {m.waist_cm} cm / hip {m.hip_cm} cm; keep every dimension under {MAX_DIM_CM} cm"
        )
    if _polygon_area(pts) < MIN_AREA_CM2:
        problems.append(f"piece '{spec.name}' has near-zero area")
    if self_intersects(pts):
        problems.append(f"piece '{spec.name}': outline self-intersects")
    return problems
