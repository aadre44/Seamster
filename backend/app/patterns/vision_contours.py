"""Patternize vision-detected piece contours into PieceSpecs (novel-piece tier 5).

The vision model returns ``piece_contours`` for pieces it can see but cannot
name with any vocabulary token: a normalized outline polygon plus a scale hint
(``width_frac`` of a reference body measurement). This module turns that raw
contour into a drafting-quality piece:

  1. re-normalize the points (bbox-width = 1, aspect preserved),
  2. simplify with Ramer-Douglas-Peucker (drops vision jitter),
  3. symmetrize about the vertical centre when the shape is nearly mirror-equal
     (garment pieces are overwhelmingly symmetric; vision output rarely is),
  4. straighten edges that are almost vertical/horizontal (seam edges are
     straight far more often than vision polygons suggest),
  5. scale to cm via the reference measurement and clamp to sane bounds,
  6. attach the seam label to the declared attachment edges.

Every accepted piece carries source="vision" so the canvas styles it as a
draft, and it passes the same novel_validation checks as LLM pieces.
"""
from __future__ import annotations

import logging
import math

from app.debug_trace import add_event
from app.models.features import GarmentFeatures, PieceContour
from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.learned_pieces import _measurement_namespace
from app.patterns.novel_validation import ATTACHMENT_LABELS, validate_spec
from app.patterns.skirts import PieceSpec

logger = logging.getLogger(__name__)

# ── Tunable parameters ─────────────────────────────────────────────────────────
# These knobs control how aggressively a raw vision contour is cleaned up and
# how its real-world size is derived. Tune here; tests pin the defaults.

#: Measurement used when the contour's ``reference`` is unknown.
DEFAULT_REFERENCE = "chest_cm"
#: Clamp for the vision-estimated piece width as a fraction of the reference
#: measurement (0.03 = 3% of chest ≈ a small tab; 1.2 covers a full-width panel).
MIN_WIDTH_FRAC, MAX_WIDTH_FRAC = 0.03, 1.2
#: Final piece bounding-box clamps in cm. Below MIN the contour is rejected
#: (vision noise); above MAX the piece is scaled down to fit.
MIN_PIECE_CM = 2.0
MAX_PIECE_CM = 200.0
#: Ramer-Douglas-Peucker simplification tolerance, as a fraction of the contour
#: bbox diagonal. Higher = smoother/simpler outlines, lower = keep more vertices.
RDP_EPSILON_FRAC = 0.015
#: Edges within this many degrees of vertical/horizontal are snapped straight.
SNAP_ANGLE_DEG = 8.0
#: Mean mirror distance (in normalized units, bbox width = 1) below which the
#: contour is forced exactly symmetric about its vertical centre.
SYMMETRY_TOLERANCE = 0.06
#: Contours whose vision confidence is below this are ignored.
MIN_CONTOUR_CONFIDENCE = 0.3
#: Accepted vertex-count window for the raw contour.
MIN_CONTOUR_POINTS = 3
MAX_CONTOUR_POINTS = 24
#: A 4-point axis-aligned rectangle whose height/width ratio falls in this window
#: is treated as an untraced bounding box (the model filled the 0-1 square instead
#: of tracing the outline) and rejected. Genuine rectangular pieces — collar
#: stands, bindings, waistbands — are strips, far outside this window.
SQUARE_BOX_ASPECT = (0.85, 1.15)
#: Contours whose detail/name contains one of these words describe notions or
#: hardware, not cut fabric pieces, and are never patternized.
NOTION_WORDS = frozenset({
    "button", "buttons", "frog", "knot", "toggle", "buckle", "zip", "zipper",
    "snap", "hook", "eyelet", "grommet", "rivet", "stud", "clasp", "drawstring",
    "drawcord", "cord", "lace", "velcro",
})
#: Piece-role words used to detect a contour that re-traces a piece the engine
#: already drafted (see ``generate_vision_pieces`` ``existing_names``).
CORE_ROLE_WORDS = frozenset({
    "back", "front", "bodice", "collar", "sleeve", "cuff", "waistband", "yoke",
    "placket", "skirt", "leg", "binding", "facing", "pocket", "hood",
})
# ───────────────────────────────────────────────────────────────────────────────


def _renormalize(pts: list[Point]) -> list[Point]:
    """Translate to the origin and scale so bbox width == 1 (aspect preserved)."""
    min_x = min(p.x for p in pts)
    min_y = min(p.y for p in pts)
    w = max(p.x for p in pts) - min_x
    if w < 1e-9:
        raise ValueError("contour has zero width")
    return [Point((p.x - min_x) / w, (p.y - min_y) / w) for p in pts]


def _point_segment_dist(p: Point, a: Point, b: Point) -> float:
    ab = b - a
    denom = ab.dot(ab)
    if denom < 1e-12:
        return p.distance_to(a)
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    proj = Point(a.x + ab.x * t, a.y + ab.y * t)
    return p.distance_to(proj)


def _rdp(pts: list[Point], epsilon: float) -> list[Point]:
    """Ramer-Douglas-Peucker polyline simplification (open path)."""
    if len(pts) < 3:
        return pts
    dmax, index = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = _point_segment_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, index = d, i
    if dmax <= epsilon:
        return [pts[0], pts[-1]]
    left = _rdp(pts[: index + 1], epsilon)
    right = _rdp(pts[index:], epsilon)
    return left[:-1] + right


def _simplify_closed(pts: list[Point], epsilon: float) -> list[Point]:
    """RDP on a closed polygon: split at the two most distant vertices so the
    seam of the split doesn't erase real corners."""
    if len(pts) <= 4:
        return pts
    # split at vertex 0 and the vertex farthest from it
    far = max(range(1, len(pts)), key=lambda i: pts[0].distance_to(pts[i]))
    a = _rdp(pts[: far + 1], epsilon)
    b = _rdp(pts[far:] + [pts[0]], epsilon)
    merged = a[:-1] + b[:-1]
    return merged if len(merged) >= 3 else pts


def _symmetrize(pts: list[Point]) -> list[Point]:
    """Force exact mirror symmetry about the vertical centre when the contour is
    already nearly symmetric (mean nearest-mirror distance < SYMMETRY_TOLERANCE)."""
    cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
    mirrored = [Point(2 * cx - p.x, p.y) for p in pts]

    def nearest(q: Point) -> Point:
        return min(mirrored, key=lambda m: q.distance_to(m))

    mean_dist = sum(p.distance_to(nearest(p)) for p in pts) / len(pts)
    if mean_dist > SYMMETRY_TOLERANCE:
        return pts
    return [p.midpoint(nearest(p)) for p in pts]


def _snap_axes(pts: list[Point]) -> list[Point]:
    """Straighten closed-polygon edges that are within SNAP_ANGLE_DEG of
    vertical/horizontal by aligning each next vertex to the previous one."""
    tol = math.tan(math.radians(SNAP_ANGLE_DEG))
    out = [Point(pts[0].x, pts[0].y)]
    for i in range(1, len(pts)):
        prev, cur = out[-1], pts[i]
        dx, dy = abs(cur.x - prev.x), abs(cur.y - prev.y)
        if dx > 1e-9 and dy / max(dx, 1e-9) <= tol:
            cur = Point(cur.x, prev.y)      # nearly horizontal → horizontal
        elif dy > 1e-9 and dx / max(dy, 1e-9) <= tol:
            cur = Point(prev.x, cur.y)      # nearly vertical → vertical
        out.append(cur)
    # Closing edge (last vertex back to vertex 0): align the LAST vertex so the
    # loop straightens too — vertex 0 stays fixed as the anchor.
    first, last = out[0], out[-1]
    dx, dy = abs(first.x - last.x), abs(first.y - last.y)
    if dx > 1e-9 and dy / max(dx, 1e-9) <= tol:
        out[-1] = Point(last.x, first.y)
    elif dy > 1e-9 and dx / max(dy, 1e-9) <= tol:
        out[-1] = Point(first.x, last.y)
    return out


def _contour_words(contour: PieceContour) -> set[str]:
    text = f"{contour.detail or ''} {contour.name or ''}".lower()
    return {w for w in text.replace("_", " ").replace("/", " ").split() if w}


def _is_square_box(pts: list[Point]) -> bool:
    """True when the contour is a 4-vertex axis-aligned rectangle whose aspect is
    near 1:1 — the signature of a model that filled the normalized 0-1 square
    instead of tracing the piece's outline."""
    if len(pts) != 4:
        return False
    xs = sorted({round(p.x, 4) for p in pts})
    ys = sorted({round(p.y, 4) for p in pts})
    if len(xs) != 2 or len(ys) != 2:
        return False
    w, h = xs[1] - xs[0], ys[1] - ys[0]
    if w < 1e-9:
        return False
    return SQUARE_BOX_ASPECT[0] <= h / w <= SQUARE_BOX_ASPECT[1]


def patternize_contour(contour: PieceContour, measurements: Measurements) -> PieceSpec:
    """Convert one vision contour into a cleaned, real-scale PieceSpec.

    Raises ValueError for contours that cannot become a usable piece (too few
    points, low confidence, notions/hardware, untraced bounding boxes, degenerate
    or sub-MIN_PIECE_CM results)."""
    if contour.confidence < MIN_CONTOUR_CONFIDENCE:
        raise ValueError(
            f"contour '{contour.detail}' confidence {contour.confidence:.2f} is below "
            f"the acceptance threshold {MIN_CONTOUR_CONFIDENCE}"
        )
    notion_hits = _contour_words(contour) & NOTION_WORDS
    if notion_hits:
        raise ValueError(
            f"contour '{contour.detail}' describes a notion ({', '.join(sorted(notion_hits))}), "
            "not a cut fabric piece"
        )
    raw = [Point(p.x, p.y) for p in contour.points]
    if not MIN_CONTOUR_POINTS <= len(raw) <= MAX_CONTOUR_POINTS:
        raise ValueError(
            f"contour '{contour.detail}' has {len(raw)} points; expected "
            f"{MIN_CONTOUR_POINTS}-{MAX_CONTOUR_POINTS}"
        )
    if _is_square_box(raw):
        raise ValueError(
            f"contour '{contour.detail}' is a near-square 4-point box — an untraced "
            "bounding box, not an outline"
        )

    pts = _renormalize(raw)
    diag = math.hypot(1.0, max(p.y for p in pts))
    pts = _simplify_closed(pts, epsilon=RDP_EPSILON_FRAC * diag)
    if len(pts) < 3:
        raise ValueError(f"contour '{contour.detail}' collapsed during simplification")
    pts = _symmetrize(pts)
    pts = _snap_axes(pts)
    pts = _renormalize(pts)  # snapping/symmetrizing can shift the bbox

    # Real-world scale: bbox width = width_frac × reference measurement. Judge the
    # RAW vision estimate before clamping — an estimate far below the clamp floor
    # is noise, not a piece that happens to be small.
    ns = _measurement_namespace(measurements)
    ref = contour.reference if contour.reference in ns else DEFAULT_REFERENCE
    if ns[ref] * contour.width_frac < MIN_PIECE_CM:
        raise ValueError(
            f"contour '{contour.detail}' scales to under {MIN_PIECE_CM} cm — likely noise"
        )
    frac = max(MIN_WIDTH_FRAC, min(MAX_WIDTH_FRAC, contour.width_frac))
    width_cm = ns[ref] * frac
    height_cm = width_cm * max(p.y for p in pts)
    if max(width_cm, height_cm) > MAX_PIECE_CM:
        width_cm *= MAX_PIECE_CM / max(width_cm, height_cm)
    if width_cm * max(p.y for p in pts) < MIN_PIECE_CM:
        raise ValueError(
            f"contour '{contour.detail}' is under {MIN_PIECE_CM} cm tall — likely noise"
        )
    outline = [Point(p.x * width_cm, p.y * width_cm) for p in pts]

    edge_labels: dict[int, str] = {}
    if contour.attachment_label in ATTACHMENT_LABELS and contour.attachment_edges:
        edge_labels = {
            int(i): contour.attachment_label
            for i in contour.attachment_edges
            if 0 <= int(i) < len(outline)
        }

    span = max(p.y for p in outline)
    cx = (min(p.x for p in outline) + max(p.x for p in outline)) / 2
    name = contour.name or contour.detail.replace("_", " ").title()
    return PieceSpec(
        name=name,
        outline=outline,
        darts=[],
        grain_start=Point(cx, span * 0.15),
        grain_end=Point(cx, span * 0.85),
        cut_qty=max(1, contour.cut_qty),
        on_fold=False,
        seam_allowance=measurements.seam_allowance_cm,
        notes=(
            f"traced from the photo (vision draft, confidence {contour.confidence:.0%}); "
            "verify the shape and dimensions in the editor before cutting"
        ),
        edge_labels=edge_labels,
        source="vision",
        detail=contour.detail,
    )


def _duplicates_existing(contour: PieceContour, existing_names: set[str]) -> str | None:
    """Return the name of an already-drafted piece this contour re-traces, or None.

    A contour duplicates a drafted piece when both share a core piece-role word
    (back/front/collar/…). The vision model only sees the garment, not what the
    parametric engine drafted, so in forced-contour debug mode (and on sloppy
    normal-mode output) it happily re-traces the back panel or collar the engine
    already produced — those must not land on the canvas twice."""
    contour_roles = _contour_words(contour) & CORE_ROLE_WORDS
    if not contour_roles:
        return None
    for name in existing_names:
        name_words = set(name.lower().replace("_", " ").split())
        if contour_roles & name_words:
            return name
    return None


def generate_vision_pieces(
    features: GarmentFeatures,
    measurements: Measurements,
    existing_names: set[str] | frozenset = frozenset(),
) -> list[PieceSpec]:
    """Patternize every usable contour; invalid ones are logged and skipped.

    ``existing_names`` lists pieces already drafted by the parametric engine;
    contours that re-trace one of them are skipped."""
    specs: list[PieceSpec] = []
    for contour in features.piece_contours:
        duplicate_of = _duplicates_existing(contour, set(existing_names))
        if duplicate_of:
            logger.info(
                "Skipping vision contour '%s': engine already drafted '%s'",
                contour.detail, duplicate_of,
            )
            add_event(
                "vision_contour_skipped", detail=contour.detail,
                reason=f"duplicates drafted piece '{duplicate_of}'",
            )
            continue
        try:
            spec = patternize_contour(contour, measurements)
        except ValueError as exc:
            logger.info("Skipping vision contour '%s': %s", contour.detail, exc)
            add_event("vision_contour_skipped", detail=contour.detail, reason=str(exc))
            continue
        problems = validate_spec(spec, measurements)
        if problems:
            logger.info(
                "Vision contour '%s' failed validation: %s", contour.detail, "; ".join(problems)
            )
            add_event("vision_contour_skipped", detail=contour.detail, reason="; ".join(problems))
            continue
        xs = [p.x for p in spec.outline]
        ys = [p.y for p in spec.outline]
        add_event(
            "vision_contour_accepted", detail=contour.detail, name=spec.name,
            raw_points=len(contour.points), cleaned_points=len(spec.outline),
            width_cm=round(max(xs) - min(xs), 2), height_cm=round(max(ys) - min(ys), 2),
        )
        specs.append(spec)
    return specs
