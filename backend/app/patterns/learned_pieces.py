"""Persisted template store for LLM-generated pattern pieces.

When the LLM generates a novel piece for an unseen garment detail, its
parametric description (formulas, not absolute coordinates) is saved here.
Subsequent requests for the same detail use the template directly instead
of calling the LLM again, making the parametric engine progressively richer.
"""
from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.novel_validation import ATTACHMENT_LABELS
from app.patterns.pockets import VALID_SHAPES, make_patch_pocket
from app.patterns.skirts import PieceSpec

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).parent / "templates" / "learned.json"

# Geometry values apply_template can assemble. Anything else falls back to rectangle.
VALID_GEOMETRIES = (
    "rectangle",        # straps, ties, simple bands, casings
    "shaped_rectangle", # rectangle with a shaped bottom end (flap, tab, belt end)
    "trapezoid",        # bands/gores wider at one end
    "godet",            # triangular flare insert with a curved hem
    "quarter_circle",   # 90° annular flounce / circle-cut piece
    "half_circle",      # 180° annular flounce / cascade
    "curved_band",      # contoured band (shaped collar / curved waistband)
    "custom",           # formula-based point list — any flat piece no primitive fits
)

# All field names that are valid in formula expressions
_MEASUREMENT_VARS: frozenset[str] = frozenset({
    "waist_cm", "hip_cm", "waist_to_hip_cm", "length_cm",
    "waistband_width_cm", "seam_allowance_cm", "hem_allowance_cm",
    "chest_cm", "shoulder_width_cm", "arm_length_cm",
    "inseam_cm", "rise_cm",
})

# Sensible fallbacks for optional measurements that may be None
_MEASUREMENT_DEFAULTS: dict[str, float] = {
    "chest_cm": 90.0,
    "shoulder_width_cm": 38.0,
    "arm_length_cm": 60.0,
    "inseam_cm": 76.0,
    "rise_cm": 28.0,
}


class PieceTemplate(BaseModel):
    """Parametric description of a novel piece learned from LLM output.

    Dimensions are stored as formula strings (arithmetic expressions using
    measurement variable names) so the template can be re-evaluated for any
    body size. The geometry field controls how the formula values are
    assembled into a PieceSpec outline.
    """
    id: str                          # e.g. "spaghetti_straps-shirt-v1"
    trigger_detail: str              # feature detail string that activates this piece
    garment_types: list[str]         # garment types this applies to
    name: str                        # piece name shown on the pattern
    description: str
    geometry: str                    # one of VALID_GEOMETRIES (future: "custom")
    length_formula: str              # e.g. "shoulder_width_cm * 1.8"
    width_formula: str               # e.g. "1.5"
    cut_qty: int = 2
    on_fold: bool = False
    seam_allowance_formula: str = "seam_allowance_cm"
    grain_direction: str = "length"  # "length" (along Y) | "width" (along X)
    created_at: str = ""
    times_used: int = 0
    # Geometry-specific extras (ignored by geometries that don't use them)
    top_width_formula: str | None = None    # trapezoid: top edge width
    curve_depth_formula: str | None = None  # curved_band: arc rise (default length * 0.12)
    end_shape: str = "square"               # shaped_rectangle: square|rounded|angled|pointed|curved
    # Garment edge this piece is sewn to (one of novel_validation.ATTACHMENT_LABELS, or
    # None for applied/free-standing pieces). When set, the geometry's intrinsic
    # attachment edge(s) get this seamLabel so _compute_connections pairs them.
    attachment_label: str | None = None
    # Custom geometry only: the outline as ordered points whose coordinates are
    # formula strings — {"x": "...", "y": "..."} plus optional "cp1x"/"cp1y"/
    # "cp2x"/"cp2y" to reach the vertex along a cubic bezier from the previous
    # one. The outline closes automatically from the last point to the first.
    points: list[dict] | None = None
    # Custom geometry only: 0-based outline edge indices (edge i runs from point i
    # to point i+1) that carry attachment_label. Other geometries know their
    # attachment edges intrinsically.
    attachment_edges: list[int] | None = None


class TemplateStore:
    """JSON-backed store for PieceTemplates.

    Loads once from disk on first access. Writes back on every add or
    times_used update. Thread-safety is not required for single-process use.
    """

    def __init__(self, path: Path = TEMPLATES_PATH) -> None:
        self._path = path
        self._templates: list[PieceTemplate] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._templates = [PieceTemplate(**t) for t in raw.get("pieces", [])]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"pieces": [t.model_dump() for t in self._templates]}
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def find(self, detail: str, garment_type: str) -> PieceTemplate | None:
        """Return the first template matching the detail + garment type, or None."""
        for t in self._templates:
            if t.trigger_detail == detail and garment_type in t.garment_types:
                return t
        return None

    def add(self, template: PieceTemplate) -> None:
        """Insert or replace a template by id, then persist."""
        self._templates = [t for t in self._templates if t.id != template.id]
        self._templates.append(template)
        self._save()

    def remove(self, template_id: str) -> bool:
        """Remove a template by id. Returns True if found and removed."""
        before = len(self._templates)
        self._templates = [t for t in self._templates if t.id != template_id]
        if len(self._templates) < before:
            self._save()
            return True
        return False

    def record_use(self, template_id: str) -> None:
        """Increment the times_used counter for a template, then persist."""
        for t in self._templates:
            if t.id == template_id:
                t.times_used += 1
        self._save()

    @property
    def all_templates(self) -> list[PieceTemplate]:
        return list(self._templates)


# ── Formula evaluation ────────────────────────────────────────────────────────

def _eval_formula(formula: str, ns: dict[str, Any]) -> float:
    """Safely evaluate an arithmetic formula string against a variable namespace.

    Only measurement variable names, the functions max/min, numeric literals,
    and arithmetic operators (+, -, *, /, parentheses) are permitted.
    Raises ValueError for any formula that doesn't pass validation.
    """
    # Validate: replace known identifiers, then check only safe characters remain
    test = formula
    allowed_names = _MEASUREMENT_VARS | {"max", "min"}
    for name in sorted(allowed_names, key=len, reverse=True):
        test = test.replace(name, "1")
    if not re.match(r"^[\d\s\.\+\-\*\/\(\)\,]+$", test):
        raise ValueError(f"Unsafe formula expression: {formula!r}")

    safe_ns = {**ns, "max": max, "min": min, "__builtins__": {}}
    return float(eval(formula, safe_ns))  # noqa: S307 — validated above


def _measurement_namespace(m: Measurements) -> dict[str, float]:
    ns: dict[str, float] = {}
    for field in _MEASUREMENT_VARS:
        val = getattr(m, field, None)
        ns[field] = val if val is not None else _MEASUREMENT_DEFAULTS.get(field, 0.0)
    return ns


# ── Geometry builders ─────────────────────────────────────────────────────────
# Each returns (outline, (grain_start, grain_end)) in local coordinates; the
# caller normalises the piece into the +x/+y quadrant afterwards.

Outline = list  # list[Point | CurveSegment]
_Grain = tuple  # (Point, Point)

# Bezier "magic number" handle fraction for a 90° arc (matches pockets.py).
_KAPPA = 0.5523


def _rectangle_outline(length: float, width: float, grain_direction: str) -> tuple[Outline, _Grain]:
    if grain_direction == "length":
        # Piece stands vertically: width along X, length along Y
        outline = [
            Point(0.0, 0.0),
            Point(width, 0.0),
            Point(width, length),
            Point(0.0, length),
        ]
        grain = (Point(width / 2, length * 0.1), Point(width / 2, length * 0.9))
    else:
        # Piece lies horizontally: length along X, width along Y
        outline = [
            Point(0.0, 0.0),
            Point(length, 0.0),
            Point(length, width),
            Point(0.0, width),
        ]
        grain = (Point(length * 0.1, width / 2), Point(length * 0.9, width / 2))
    return outline, grain


def _trapezoid_outline(length: float, bottom_w: float, top_w: float) -> tuple[Outline, _Grain]:
    """Four-sided band/gore: top and bottom edges centred, joined by slanted sides."""
    bbox_w = max(bottom_w, top_w)
    tx0 = (bbox_w - top_w) / 2
    bx0 = (bbox_w - bottom_w) / 2
    outline = [
        Point(tx0, 0.0),
        Point(tx0 + top_w, 0.0),
        Point(bx0 + bottom_w, length),
        Point(bx0, length),
    ]
    grain = (Point(bbox_w / 2, length * 0.1), Point(bbox_w / 2, length * 0.9))
    return outline, grain


def _godet_outline(length: float, width: float) -> tuple[Outline, _Grain]:
    """Flare insert: apex at the top, two straight sides of exactly ``length``
    (the slit they are sewn into), and a circular hem arc through (width/2, length).

    ``width`` is clamped below 2×length so the hem corners stay on the radius circle.
    """
    w = min(width, 1.8 * length)
    half = w / 2
    drop = math.sqrt(max(length**2 - half**2, 0.0))  # y of the hem corners
    sag = length - drop                              # arc rise below the corner chord
    outline = [
        Point(half, 0.0),                            # apex
        Point(w, drop),                              # right hem corner (side = length)
        CurveSegment(0.0, drop,                      # hem arc, bulging down to y=length
                     cp1=Point(w * 0.72, drop + sag * 4.0 / 3.0),
                     cp2=Point(w * 0.28, drop + sag * 4.0 / 3.0)),
    ]
    grain = (Point(half, length * 0.15), Point(half, drop * 0.9))
    return outline, grain


def _arc_segments(
    cx: float, cy: float, r: float, a0: float, a1: float,
) -> tuple[Point, list[CurveSegment]]:
    """Approximate a circular arc from angle a0 to a1 (radians, either direction)
    as cubic beziers of at most 90° each. Returns (start_vertex, segments)."""
    n = max(1, math.ceil(abs(a1 - a0) / (math.pi / 2 + 1e-9)))
    start = Point(cx + r * math.cos(a0), cy + r * math.sin(a0))
    segs: list[CurveSegment] = []
    for i in range(n):
        t0 = a0 + (a1 - a0) * i / n
        t1 = a0 + (a1 - a0) * (i + 1) / n
        h = (4.0 / 3.0) * math.tan((t1 - t0) / 4) * r  # signed handle length
        p0 = Point(cx + r * math.cos(t0), cy + r * math.sin(t0))
        p1 = Point(cx + r * math.cos(t1), cy + r * math.sin(t1))
        segs.append(CurveSegment(
            p1.x, p1.y,
            cp1=Point(p0.x - h * math.sin(t0), p0.y + h * math.cos(t0)),
            cp2=Point(p1.x + h * math.sin(t1), p1.y - h * math.cos(t1)),
        ))
    return start, segs


def _annular_outline(attach_len: float, depth: float, sweep: float) -> tuple[Outline, _Grain]:
    """Annular sector (flounce/ruffle/circle-cut): the inner arc measures exactly
    ``attach_len`` (the edge it is sewn to) and the piece is ``depth`` deep."""
    inner_r = max(attach_len / sweep, 0.5)
    outer_r = inner_r + depth
    in_start, in_segs = _arc_segments(0.0, 0.0, inner_r, 0.0, sweep)
    out_start, out_segs = _arc_segments(0.0, 0.0, outer_r, sweep, 0.0)
    # inner arc forward, radial edge (implicit line), outer arc back, closing radial edge
    outline = [in_start, *in_segs, out_start, *out_segs]
    mid = sweep / 2
    g0, g1 = inner_r + 0.15 * depth, inner_r + 0.85 * depth
    grain = (
        Point(g0 * math.cos(mid), g0 * math.sin(mid)),
        Point(g1 * math.cos(mid), g1 * math.sin(mid)),
    )
    return outline, grain


def _curved_band_outline(length: float, width: float, depth: float) -> tuple[Outline, _Grain]:
    """Contoured band: two parallel bow-shaped edges a constant ``width`` apart,
    rising by ``depth`` at the centre (shaped collar / contoured waistband)."""
    d = max(0.0, min(depth, length * 0.4))
    bow = d * 4.0 / 3.0  # cubic through-midpoint control height for a rise of d
    outline = [
        Point(0.0, 0.0),
        CurveSegment(length, 0.0,
                     cp1=Point(length / 3, bow), cp2=Point(2 * length / 3, bow)),
        Point(length, width),
        CurveSegment(0.0, width,
                     cp1=Point(2 * length / 3, width + bow), cp2=Point(length / 3, width + bow)),
    ]
    grain = (Point(length / 2, d + width * 0.15), Point(length / 2, d + width * 0.85))
    return outline, grain


_CP_KEYS = ("cp1x", "cp1y", "cp2x", "cp2y")


def _custom_outline(points: list[dict] | None, ns: dict) -> tuple[Outline, _Grain]:
    """Evaluate a formula-based point list into an outline (custom geometry).

    Raises ValueError with a repair-loop-friendly message for malformed input:
    fewer than 3 points, non-object points, missing coordinates, or unsafe
    formulas (via _eval_formula). An explicit closing duplicate of the first
    point is dropped — the outline closes implicitly.
    """
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError(
            "custom geometry requires a 'points' array of at least 3 point objects"
        )
    if len(points) > 24:
        raise ValueError("custom geometry supports at most 24 points")

    outline: Outline = []
    for i, pt in enumerate(points):
        if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
            raise ValueError(
                f"custom point {i} must be an object with 'x' and 'y' formula strings"
            )
        x = _eval_formula(str(pt["x"]), ns)
        y = _eval_formula(str(pt["y"]), ns)
        if all(k in pt for k in _CP_KEYS):
            outline.append(CurveSegment(
                x, y,
                cp1=Point(_eval_formula(str(pt["cp1x"]), ns), _eval_formula(str(pt["cp1y"]), ns)),
                cp2=Point(_eval_formula(str(pt["cp2x"]), ns), _eval_formula(str(pt["cp2y"]), ns)),
            ))
        else:
            outline.append(Point(x, y))

    first, last = outline[0], outline[-1]
    if (
        len(outline) > 3
        and isinstance(last, Point)
        and abs(last.x - first.x) < 1e-6
        and abs(last.y - first.y) < 1e-6
    ):
        outline.pop()

    xs = [v.x for v in outline]
    ys = [v.y for v in outline]
    cx = (min(xs) + max(xs)) / 2
    span = max(ys) - min(ys)
    grain = (Point(cx, min(ys) + span * 0.15), Point(cx, min(ys) + span * 0.85))
    return outline, grain


def _normalise(outline: Outline, grain: _Grain) -> tuple[Outline, _Grain]:
    """Translate the piece so its vertex bounding box starts at (0, 0)."""
    min_x = min(v.x for v in outline)
    min_y = min(v.y for v in outline)
    if abs(min_x) < 1e-9 and abs(min_y) < 1e-9:
        return outline, grain
    dx, dy = -min_x, -min_y
    shifted: Outline = []
    for v in outline:
        if isinstance(v, CurveSegment):
            shifted.append(CurveSegment(
                v.x + dx, v.y + dy,
                cp1=Point(v.cp1.x + dx, v.cp1.y + dy),
                cp2=Point(v.cp2.x + dx, v.cp2.y + dy),
            ))
        else:
            shifted.append(Point(v.x + dx, v.y + dy))
    g0, g1 = grain
    return shifted, (Point(g0.x + dx, g0.y + dy), Point(g1.x + dx, g1.y + dy))


# ── Template → PieceSpec ──────────────────────────────────────────────────────

def apply_template(template: PieceTemplate, m: Measurements) -> PieceSpec:
    """Evaluate a PieceTemplate's formulas against concrete measurements → PieceSpec."""
    ns = _measurement_namespace(m)
    length = _eval_formula(template.length_formula, ns)
    width = _eval_formula(template.width_formula, ns)
    seam = _eval_formula(template.seam_allowance_formula, ns)
    if length <= 0 or width <= 0:
        raise ValueError(
            f"Template {template.id!r} evaluated to non-positive dimensions "
            f"(length={length}, width={width})"
        )

    geometry = template.geometry
    if geometry not in VALID_GEOMETRIES:
        logger.warning(
            "Unknown geometry %r on template %r — falling back to rectangle",
            geometry, template.id,
        )
        geometry = "rectangle"

    # Outline edge indices that carry the attachment seamLabel, per geometry.
    # Edge i runs from outline[i] to outline[i+1] (wrapping); index 0 is the top
    # edge for the rectangular family, the inner arc for flounces, the two
    # straight sides for a godet.
    attach_edges: tuple[int, ...] = (0,)

    if geometry == "shaped_rectangle":
        shape = template.end_shape if template.end_shape in VALID_SHAPES else "square"
        spec = make_patch_pocket(
            template.name, width, length, seam,
            shape=shape, cut_qty=template.cut_qty,
            notes=template.description,
        )
        spec.on_fold = template.on_fold
        if template.attachment_label in ATTACHMENT_LABELS:
            spec.edge_labels = {0: template.attachment_label}
        return spec

    if geometry == "custom":
        outline, grain = _custom_outline(template.points, ns)
        attach_edges = tuple(
            int(i) for i in (template.attachment_edges or [])
            if isinstance(i, (int, float)) and 0 <= int(i) < len(outline)
        )
    elif geometry == "trapezoid":
        top_w = (
            _eval_formula(template.top_width_formula, ns)
            if template.top_width_formula else width * 0.5
        )
        outline, grain = _trapezoid_outline(length, width, max(top_w, 0.5))
    elif geometry == "godet":
        outline, grain = _godet_outline(length, width)
        attach_edges = (0, 2)  # the two straight sides sew into the slit
    elif geometry in ("quarter_circle", "half_circle"):
        sweep = math.pi / 2 if geometry == "quarter_circle" else math.pi
        outline, grain = _annular_outline(length, width, sweep)
        # inner arc = one bezier edge per 90° of sweep, starting at edge 0
        attach_edges = tuple(range(max(1, math.ceil(sweep / (math.pi / 2 + 1e-9)))))
    elif geometry == "curved_band":
        depth = (
            _eval_formula(template.curve_depth_formula, ns)
            if template.curve_depth_formula else length * 0.12
        )
        outline, grain = _curved_band_outline(length, width, depth)
    else:
        outline, grain = _rectangle_outline(length, width, template.grain_direction)

    outline, grain = _normalise(outline, grain)
    edge_labels: dict[int, str] = {}
    if template.attachment_label in ATTACHMENT_LABELS:
        edge_labels = {i: template.attachment_label for i in attach_edges}
    return PieceSpec(
        name=template.name,
        outline=outline,
        darts=[],
        grain_start=grain[0],
        grain_end=grain[1],
        cut_qty=template.cut_qty,
        on_fold=template.on_fold,
        seam_allowance=seam,
        notes=template.description,
        edge_labels=edge_labels,
    )


# ── Module-level singleton ────────────────────────────────────────────────────

_store: TemplateStore | None = None


def get_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store
