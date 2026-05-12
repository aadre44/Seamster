"""Orchestrates the full pattern generation pipeline and serialises to .psnap JSON.

.psnap format (matches what the Phase 1 frontend saves/loads):
{
  "version": 1,
  "elements": [
    { "id": "...", "type": "line",       "start": {"x":…,"y":…}, "end": {"x":…,"y":…},
      "isFold": false, "pieceId": "…" },
    { "id": "...", "type": "grain-line", "start": …, "end": …,   "pieceId": "…" },
    ...
  ],
  "pieces": [
    { "id": "…", "name": "…", "elementIds": ["…",…], "cutQty": 2,
      "onFold": false, "seamAllowance": 1.5, "closed": true }
  ],
  "measurements": { "waist": 76, "hip": 94, "waistToHip": 21, "skirtLength": 65 }
}
"""
from __future__ import annotations

import uuid

from app.models.features import SkirtFeatures
from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.modifiers import apply_feature_modifiers, apply_silhouette
from app.patterns.skirts import DartSpec, PieceSpec, build_straight_skirt_block


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _pt(p: Point) -> dict:
    return {"x": round(p.x, 4), "y": round(p.y, 4)}


def _make_line(start: Point, end: Point, piece_id: str, is_fold: bool = False) -> dict:
    return {
        "id": _uid(),
        "type": "line",
        "start": _pt(start),
        "end": _pt(end),
        "isFold": is_fold,
        "pieceId": piece_id,
    }


def _make_grain_line(start: Point, end: Point, piece_id: str) -> dict:
    return {
        "id": _uid(),
        "type": "grain-line",
        "start": _pt(start),
        "end": _pt(end),
        "pieceId": piece_id,
    }


# ── Piece serialisation ───────────────────────────────────────────────────────

def _serialise_piece(
    spec: PieceSpec,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[list[dict], dict]:
    """Convert a PieceSpec to (elements_list, piece_dict) in .psnap format.

    offset_x / offset_y shift all coordinates so pieces are laid out side-by-side
    without overlapping on the canvas.
    """
    piece_id = _uid()
    elements: list[dict] = []
    outline_ids: list[str] = []

    def shifted(p: Point) -> Point:
        return Point(p.x + offset_x, p.y + offset_y)

    # ── Outline (closed polygon of LineElements) ──────────────────────────────
    n = len(spec.outline)
    for i in range(n):
        start = shifted(spec.outline[i])
        end = shifted(spec.outline[(i + 1) % n])

        # The CF/CB edge (last → first, i.e. i == n-1) is a fold line when on_fold=True
        is_fold = (i == n - 1) and spec.on_fold

        elem = _make_line(start, end, piece_id, is_fold=is_fold)
        elements.append(elem)
        outline_ids.append(elem["id"])

    # ── Dart markings (interior lines, NOT in outline_ids) ───────────────────
    for dart in spec.darts:
        tip = shifted(Point(dart.center_x, dart.depth))
        leg_l = shifted(Point(dart.center_x - dart.width / 2, 0.0))
        leg_r = shifted(Point(dart.center_x + dart.width / 2, 0.0))
        elements.append(_make_line(leg_l, tip, piece_id))
        elements.append(_make_line(leg_r, tip, piece_id))

    # ── Grain line ────────────────────────────────────────────────────────────
    gl = _make_grain_line(shifted(spec.grain_start), shifted(spec.grain_end), piece_id)
    elements.append(gl)

    piece_dict = {
        "id": piece_id,
        "name": spec.name,
        "elementIds": outline_ids,
        "cutQty": spec.cut_qty,
        "onFold": spec.on_fold,
        "seamAllowance": spec.seam_allowance,
        "closed": True,
    }

    return elements, piece_dict


# ── Waistband ─────────────────────────────────────────────────────────────────

def _make_waistband(features: SkirtFeatures, measurements: Measurements, offset_x: float, offset_y: float) -> tuple[list[dict], dict]:
    """Generate a straight or contoured waistband piece."""
    wb = features.waistband
    if wb.type in ("elastic", "facing"):
        # These don't have a separate waistband piece cut
        return [], {}

    wb_width = wb.width_cm_estimate
    # Width of the waistband strip: full waist + seam allowances, doubled for fold
    strip_width = measurements.waist_cm / 2 + measurements.seam_allowance_cm * 2
    strip_height = wb_width * 2  # fold on long edge

    piece_id = _uid()
    corners = [
        Point(offset_x, offset_y),
        Point(offset_x + strip_width, offset_y),
        Point(offset_x + strip_width, offset_y + strip_height),
        Point(offset_x, offset_y + strip_height),
    ]

    elements: list[dict] = []
    outline_ids: list[str] = []
    n = len(corners)
    for i in range(n):
        is_fold = (i == 2)  # bottom edge is fold line
        elem = _make_line(corners[i], corners[(i + 1) % n], piece_id, is_fold=is_fold)
        elements.append(elem)
        outline_ids.append(elem["id"])

    # Grain line runs lengthwise
    grain = _make_grain_line(
        Point(offset_x + 1.0, offset_y + strip_height / 2),
        Point(offset_x + strip_width - 1.0, offset_y + strip_height / 2),
        piece_id,
    )
    elements.append(grain)

    piece_dict = {
        "id": piece_id,
        "name": "Waistband",
        "elementIds": outline_ids,
        "cutQty": 1,
        "onFold": False,
        "seamAllowance": measurements.seam_allowance_cm,
        "closed": True,
    }
    return elements, piece_dict


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pattern(features: SkirtFeatures, measurements: Measurements) -> dict:
    """Return a .psnap JSON-compatible dict for the given skirt features + measurements."""

    # 1 · Build the straight base block
    base = build_straight_skirt_block(measurements)

    # 2 · Apply silhouette modifier (pencil / a-line / circle / etc.)
    pieces = apply_silhouette(base, features, measurements)

    # 3 · Apply feature-level modifiers (closure, details, etc.)
    pieces = apply_feature_modifiers(pieces, features, measurements)

    # 4 · Serialise to .psnap
    all_elements: list[dict] = []
    all_pieces: list[dict] = []

    # Lay pieces out on the canvas with a 5 cm gap between them
    gap = 5.0
    cursor_x = 2.0   # start 2 cm from left edge

    for spec in pieces.values():
        # Compute piece bounding-box width
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    # 5 · Waistband (if applicable)
    wb_elems, wb_piece = _make_waistband(features, measurements, offset_x=cursor_x, offset_y=2.0)
    all_elements.extend(wb_elems)
    if wb_piece:
        all_pieces.append(wb_piece)

    # 6 · Measurements block (using frontend field names)
    meas_dict = {
        "waist": measurements.waist_cm,
        "hip": measurements.hip_cm,
        "waistToHip": measurements.waist_to_hip_cm,
        "skirtLength": measurements.length_cm,
    }

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": meas_dict,
    }
