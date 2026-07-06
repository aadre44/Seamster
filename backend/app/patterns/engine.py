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
  "measurements": { "waist": 76, "hip": 94, "waistToHip": 21, "garmentLength": 65 }
}
"""
from __future__ import annotations

import math
import uuid

from collections import namedtuple

from app.models.features import Construction, GarmentFeatures, GarmentType, ShapeMode
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.llm_fallback import detect_unsupported_details, generate_novel_pieces
from app.patterns.modifiers import apply_feature_modifiers, apply_silhouette
from app.patterns.dresses import build_dress_block
from app.patterns.jackets import build_jacket_block
from app.patterns.pleats import apply_pleats, pleat_unit_allowance
from app.patterns.pockets import make_patch_pocket
from app.patterns.shirts import build_shirt_block
from app.patterns.skirts import DartSpec, PieceSpec, build_skirt_block, build_straight_skirt_block
from app.patterns.trousers import build_trousers_block
from app.patterns.shaping import apply_shape
from app.patterns.vests import build_vest_block


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


def _make_curve(start: Point, cp1: Point, cp2: Point, end: Point, piece_id: str) -> dict:
    return {
        "id": _uid(),
        "type": "curve",
        "start": _pt(start),
        "cp1": _pt(cp1),
        "cp2": _pt(cp2),
        "end": _pt(end),
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
    """Convert a PieceSpec to (elements_list, piece_dict) in .psnap format."""
    piece_id = _uid()
    elements: list[dict] = []
    outline_ids: list[str] = []

    def shifted(p: Point) -> Point:
        return Point(p.x + offset_x, p.y + offset_y)

    # ── Outline (closed polygon of Line/Curve elements) ───────────────────────
    n = len(spec.outline)
    for i in range(n):
        a = spec.outline[i]
        b = spec.outline[(i + 1) % n]

        s = shifted(a)
        e = shifted(Point(b.x, b.y))

        # The CF/CB edge (last → first, i.e. i == n-1) is a fold line when on_fold=True
        is_fold = (i == n - 1) and spec.on_fold

        if isinstance(b, CurveSegment):
            elem = _make_curve(s, shifted(b.cp1), shifted(b.cp2), e, piece_id)
        else:
            elem = _make_line(s, e, piece_id, is_fold=is_fold)
        elem["seamLabel"] = spec.edge_labels.get(i, "")
        elements.append(elem)
        outline_ids.append(elem["id"])

    # ── Dart markings (interior lines, NOT in outline_ids) ───────────────────
    def _baseline_y(dart: "DartSpec", x: float) -> float:
        """y of the waist edge at x: 0 by default, or interpolated along a slanted
        baseline (used by the tilted trouser back waist)."""
        base = getattr(dart, "baseline", None)
        if base is None:
            return 0.0
        a, b = base
        if abs(b.x - a.x) < 1e-9:
            return a.y
        t = (x - a.x) / (b.x - a.x)
        return a.y + t * (b.y - a.y)

    for dart in spec.darts:
        x_l = dart.center_x - dart.width / 2
        x_r = dart.center_x + dart.width / 2
        y_l = _baseline_y(dart, x_l)
        y_r = _baseline_y(dart, x_r)
        y_c = _baseline_y(dart, dart.center_x)
        tip = shifted(Point(dart.center_x, y_c + dart.depth))
        leg_l = shifted(Point(x_l, y_l))
        leg_r = shifted(Point(x_r, y_r))
        elements.append(_make_line(leg_l, tip, piece_id))
        elements.append(_make_line(leg_r, tip, piece_id))

    # ── Pleat markings (interior lines, NOT in outline_ids) ──────────────────
    # Each pleat draws a dashed fold line (the crease that sits on top) and a
    # solid placement line (where the fold is brought to), plus a short tick at
    # the top showing the fold direction. These are skipped by
    # _compute_connections because they are not in outline_ids.
    for pleat in getattr(spec, "pleats", []):
        fold_el = _make_line(
            shifted(Point(pleat.fold_x, pleat.y_top)),
            shifted(Point(pleat.fold_x, pleat.y_bottom)),
            piece_id, is_fold=True,
        )
        fold_el["seamLabel"] = "pleat_fold"
        elements.append(fold_el)

        place_el = _make_line(
            shifted(Point(pleat.placement_x, pleat.y_top)),
            shifted(Point(pleat.placement_x, pleat.y_bottom)),
            piece_id,
        )
        place_el["seamLabel"] = "pleat_placement"
        elements.append(place_el)

        # Direction tick: a short diagonal from the fold line toward the placement
        # line, just below the top edge — shows which way the pleat is folded.
        tick_dir = 1.0 if pleat.placement_x >= pleat.fold_x else -1.0
        tick_run = min(2.0, abs(pleat.placement_x - pleat.fold_x) or 2.0)
        tick_y = pleat.y_top + min(2.0, (pleat.y_bottom - pleat.y_top) * 0.1)
        tick_el = _make_line(
            shifted(Point(pleat.fold_x, pleat.y_top)),
            shifted(Point(pleat.fold_x + tick_dir * tick_run, tick_y)),
            piece_id,
        )
        tick_el["seamLabel"] = "pleat_fold"
        elements.append(tick_el)

    # ── Interior construction marks (fly fold/topstitch, crease) ─────────────
    # Emitted as standalone interior elements; NOT added to outline_ids, so they are
    # ignored by _compute_connections and never become seams.
    for mark in getattr(spec, "marks", []):
        pts = mark.points
        for j in range(len(pts) - 1):
            a = pts[j]
            b = pts[j + 1]
            s = shifted(Point(a.x, a.y))
            e = shifted(Point(b.x, b.y))
            if isinstance(b, CurveSegment):
                el = _make_curve(s, shifted(b.cp1), shifted(b.cp2), e, piece_id)
            else:
                el = _make_line(s, e, piece_id, is_fold=mark.dashed)
            el["seamLabel"] = mark.label
            elements.append(el)

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
        "notes": spec.notes,
        "source": spec.source,
    }
    if spec.detail:
        piece_dict["detail"] = spec.detail

    return elements, piece_dict


# ── Waistband ─────────────────────────────────────────────────────────────────

def _make_waistband(features: GarmentFeatures, measurements: Measurements, offset_x: float, offset_y: float) -> tuple[list[dict], dict]:
    """Generate a straight or contoured waistband piece."""
    wb = features.waistband
    if wb is None or wb.type in ("elastic", "facing"):
        return [], {}

    wb_width = wb.width_cm_estimate
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
    _wb_labels = {0: "waist"}
    for i in range(n):
        is_fold = (i == 2)  # bottom edge is fold line
        elem = _make_line(corners[i], corners[(i + 1) % n], piece_id, is_fold=is_fold)
        elem["seamLabel"] = _wb_labels.get(i, "")
        elements.append(elem)
        outline_ids.append(elem["id"])

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


# ── Seam connection computation ───────────────────────────────────────────────

def _edge_length(elem: dict) -> float:
    """Approximate length of a serialised outline edge (curves are sampled)."""
    sx, sy = elem["start"]["x"], elem["start"]["y"]
    ex, ey = elem["end"]["x"], elem["end"]["y"]
    if elem.get("type") != "curve":
        return math.hypot(ex - sx, ey - sy)
    c1x, c1y = elem["cp1"]["x"], elem["cp1"]["y"]
    c2x, c2y = elem["cp2"]["x"], elem["cp2"]["y"]
    length = 0.0
    px, py = sx, sy
    n = 16
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        x = mt**3 * sx + 3 * mt**2 * t * c1x + 3 * mt * t**2 * c2x + t**3 * ex
        y = mt**3 * sy + 3 * mt**2 * t * c1y + 3 * mt * t**2 * c2y + t**3 * ey
        length += math.hypot(x - px, y - py)
        px, py = x, y
    return length


def _compute_connections(all_elements: list[dict], all_pieces: list[dict]) -> list[dict]:
    """Pair edges that share the same non-empty seamLabel across different pieces.

    Edges are grouped per (label, piece) in outline order, and for each pair of
    pieces sharing a label they are matched 1:1 by sequence — k-th edge with k-th
    edge — NOT as a cross-product (a trouser side seam split over 4 edges per leg
    previously produced 4x4 = 16 connections for one physical seam, and the
    AssemblyView aligned on an arbitrary one). If the two pieces traverse the seam
    in opposite outline directions, the reversed pairing is detected by total
    length mismatch (sewn seam segments have matching lengths) and corrected.
    With unequal edge counts the extras are left unconnected.
    """
    from itertools import combinations

    outline_ids: set[str] = set()
    for p in all_pieces:
        outline_ids.update(p["elementIds"])

    # label -> pieceId -> edges in outline order (dicts preserve insertion order)
    label_groups: dict[str, dict[str, list[dict]]] = {}
    for elem in all_elements:
        if elem["id"] not in outline_ids:
            continue
        label = elem.get("seamLabel", "")
        if not label or elem.get("isFold"):
            continue
        label_groups.setdefault(label, {}).setdefault(elem["pieceId"], []).append(elem)

    connections: list[dict] = []
    for label, by_piece in label_groups.items():
        for pid_a, pid_b in combinations(by_piece.keys(), 2):
            edges_a = by_piece[pid_a]
            edges_b = by_piece[pid_b]
            if len(edges_a) > 1 and len(edges_b) > 1:
                forward = sum(abs(_edge_length(a) - _edge_length(b)) for a, b in zip(edges_a, edges_b))
                reverse = sum(abs(_edge_length(a) - _edge_length(b)) for a, b in zip(edges_a, reversed(edges_b)))
                if reverse < forward:
                    edges_b = list(reversed(edges_b))
            for a, b in zip(edges_a, edges_b):
                connections.append({
                    "label": label,
                    "from": {"pieceId": pid_a, "edgeId": a["id"]},
                    "to":   {"pieceId": pid_b, "edgeId": b["id"]},
                })
    return connections


# ── Pocket shape + pleat resolution ───────────────────────────────────────────

_POCKET_SHAPE_TOKENS: dict[str, str] = {
    "pocket_pointed": "pointed",
    "pocket_rounded": "rounded",
    "pocket_angled":  "angled",
    "pocket_curved":  "curved",
}


def _pocket_shape(details: list[str]) -> str:
    """Map the detected pocket-shape detail token to a make_patch_pocket shape."""
    for token, shape in _POCKET_SHAPE_TOKENS.items():
        if token in details:
            return shape
    return "square"


_ResolvedPleats = namedtuple("_ResolvedPleats", "kind count depth placement")

# Default finished pleat depth (cm) when the analysis did not estimate one.
_DEFAULT_PLEAT_DEPTH = 3.0


def _resolve_pleats(
    features: GarmentFeatures,
    *,
    default_placement: str,
    waist_cm: float,
) -> _ResolvedPleats | None:
    """Normalise pleat detection into (kind, count, depth, placement) or None.

    Covers three signals, in priority order:
      1. the structured ``features.pleats`` PleatDetail,
      2. the legacy ``pleated`` skirt silhouette,
      3. a bare ``"pleats"`` / ``"pleated"`` detail token.
    Auto-sizes count (from the waist) and depth when the analysis left them blank.
    ``count`` is interpreted as pleats *per panel* by the garment wiring.
    """
    pd = getattr(features, "pleats", None)
    details = features.details or []
    silhouette = (features.silhouette or "").lower()

    structured = (
        pd is not None
        and getattr(pd, "type", "none") != "none"
        and (pd.count > 0 or pd.placement != "none")
    )
    legacy = silhouette == "pleated" or "pleats" in details or "pleated" in details
    if not structured and not legacy:
        return None

    kind = pd.type if (structured and pd.type != "none") else "knife"
    placement = pd.placement if (structured and pd.placement != "none") else default_placement
    depth = pd.depth_cm if (structured and pd.depth_cm > 0) else _DEFAULT_PLEAT_DEPTH

    count = pd.count if (structured and pd.count > 0) else 0
    if count <= 0:
        if placement in ("all_around", "skirt"):
            # Roughly one pleat per ~6 cm of finished waist-quarter, min 3 per panel.
            count = max(3, int((waist_cm / 4) / 6))
        elif placement in ("front_waist", "back_waist"):
            count = 2
        else:
            count = 1
    # A photo counts pleats across the whole garment; panels are cut in pairs,
    # so halve an all-around count to get a sensible per-panel figure.
    elif placement in ("all_around", "skirt") and count > 3:
        count = max(2, count // 2)

    return _ResolvedPleats(kind, count, depth, placement)


def _resolve_construction(features: GarmentFeatures) -> Construction:
    """Return the garment's Construction, defaulting sensibly when the analysis omitted it.

    Falls back to the neckline: ``halter`` ⇒ an integral halter strap, ``strapless`` ⇒
    strapless. This keeps older analyses (which only set ``neckline``) producing the
    right topology even without a structured ``construction`` object.
    """
    c = features.construction
    if c is not None:
        return c
    neckline = (features.neckline or "").lower()
    if neckline == "halter":
        return Construction(strap_style="halter_neck", front_opening="plunge")
    if neckline == "strapless":
        return Construction(strap_style="strapless")
    return Construction()


# ── Garment-specific generators ───────────────────────────────────────────────

def _generate_skirt_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    details = features.details if features.details else []

    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "straight": "straight", "pencil":  "pencil",  "a_line":  "a_line",
        "flared":   "flared",   "circle":  "circle",  "gathered":"gathered",
        "pleated":  "pleated",  "wrap":    "wrap",    "trumpet": "trumpet",
        "mermaid":  "mermaid",  "tulip":   "tulip",   "tiered":  "tiered",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "straight")

    # Real pleat handling: when pleats are detected, draft a clean straight panel
    # and add the fabric allowance + fold markings ourselves rather than relying on
    # the cosmetic "pleated" fit (which only flared the hem 10%).
    pleats = _resolve_pleats(features, default_placement="all_around", waist_cm=measurements.waist_cm)
    if pleats is not None:
        fit_style = "straight"

    # "maxi" maps to None in _LENGTH_CM → uses measurement directly
    _LENGTH_MAP: dict[str, str] = {
        "micro": "micro", "mini": "mini", "above_knee": "above_knee",
        "knee":  "knee",  "midi": "midi", "maxi":       "maxi",
    }
    length_category = _LENGTH_MAP.get(features.length_category or "", "maxi")

    _CLOSURE_MAP: dict[str, str] = {
        "center_back_zip": "center_back_zip",
        "center_front_zip": "side_zip",
        "side_zip":        "side_zip",
        "button_fly":      "hook_and_eye",
        "button_front":    "hook_and_eye",
        "snap_front":      "hook_and_eye",
        "double_breasted": "hook_and_eye",
        "hook_and_eye":    "hook_and_eye",
        "none":            "elastic",
    }
    closure_obj = features.closure
    raw_closure = closure_obj.type if closure_obj and hasattr(closure_obj, "type") else "none"
    closure_type = _CLOSURE_MAP.get(raw_closure, "center_back_zip")
    if features.waistband and hasattr(features.waistband, "type") and features.waistband.type == "elastic":
        closure_type = "elastic"

    pieces = build_skirt_block(
        measurements,
        fit_style=fit_style,
        length_category=length_category,
        closure_type=closure_type,
        has_side_pockets="side_pockets" in details,
        has_patch_pockets="patch_pockets" in details,
        has_patch_pocket_flap="patch_pocket_flap" in details,
        has_back_pockets="welt_pockets" in details,
        has_kick_pleat="kick_pleat" in details,
        has_side_slits="side_slits" in details,
        has_ruffle_tier="ruffle" in details,
        pocket_shape=_pocket_shape(details),
    )

    # Honour explicit AI dart-count overrides (e.g. vision returns darts.front == 0)
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front" in pieces:
            pieces["front"].darts = []
        if features.darts.back == 0 and "back" in pieces:
            pieces["back"].darts = []

    # Full-length pleats: widen the front/back panels by the pleat allowance and
    # distribute fold markings across each panel (darts are released into pleats).
    if pleats is not None:
        for key in ("front", "back"):
            spec = pieces.get(key)
            if spec is None:
                continue
            spec.darts = []
            orig_w = max(p.x for p in spec.outline)
            total = pleat_unit_allowance(pleats.kind, pleats.depth) * pleats.count
            margin = max(2.0, total * 0.08)
            apply_pleats(
                spec, insert_x=0.0, count=pleats.count, depth=pleats.depth,
                kind=pleats.kind, y_top=0.0, release_y=None,
                mark_region=(margin, orig_w + total - margin),
            )
            spec.notes = (
                f"{pleats.count} {pleats.kind.replace('_', ' ')} pleats per panel; "
                f"fold on the dashed fold line and bring to the placement line, then baste "
                f"across the top before attaching the waistband; " + (spec.notes or "")
            )

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0

    for spec in pieces.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    wb_elems, wb_piece = _make_waistband(features, measurements, offset_x=cursor_x, offset_y=2.0)
    all_elements.extend(wb_elems)
    if wb_piece:
        all_pieces.append(wb_piece)

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "waistToHip": measurements.waist_to_hip_cm,
            "garmentLength": measurements.length_cm,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _make_shirt_pocket(chest_cm: float, sa: float, shape: str = "square") -> PieceSpec:
    """Generate a single chest patch pocket piece sized from chest measurement.

    ``shape`` (square | rounded | angled | pointed | curved) controls the bottom
    edge so a pointed/chevron chest pocket is no longer flattened to a rectangle.
    """
    pocket_w = max(10.0, chest_cm * 0.13)
    pocket_h = max(12.0, chest_cm * 0.155)
    return make_patch_pocket(
        "Chest Patch Pocket", pocket_w, pocket_h, sa, shape=shape, cut_qty=1,
        notes="chest patch pocket; press under seam allowances and topstitch to the Front Bodice before assembling shoulders",
    )


def _generate_shirt_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    ease_map = {
        "slim": -2.0, "fitted": -2.0,
        "regular": 0.0,
        "relaxed": 2.0,
        "boxy": 4.0, "oversized": 6.0,
        "athletic": -1.0,
        "longline": 0.0,
    }
    ease_extra = ease_map.get(features.silhouette, 0.0)

    details = features.details

    construction = _resolve_construction(features)

    base = build_shirt_block(
        measurements,
        chest_ease_extra=ease_extra,
        fit_style=features.silhouette or "regular",
        sleeve_length=features.sleeve_length or "long",
        neckline=features.neckline or "crew",
        has_placket="button_placket" in details,
        has_collar="collar" in details,
        has_cuffs="cuffs" in details,
        has_ribbed_collar="ribbed_collar" in details,
        has_elastic_hem="elastic_hem" in details or "drawstring_hem" in details,
        strap_style=construction.strap_style,
        back_coverage=construction.back_coverage,
        front_opening=construction.front_opening,
        strap_width=construction.strap_width,
    )

    # Back centre-back pleat (e.g. dress-shirt action pleat) when pleats are
    # detected at the back. Released partway down for movement ease.
    pleats = _resolve_pleats(features, default_placement="center_back", waist_cm=measurements.waist_cm)
    if pleats is not None and pleats.placement in ("center_back", "back_waist", "all_around", "skirt"):
        back_spec = base.get("back_bodice")
        if back_spec is not None:
            body_len = max(p.y for p in back_spec.outline)
            apply_pleats(
                back_spec, insert_x=1.0, count=1, depth=pleats.depth,
                kind=pleats.kind, y_top=0.0, release_y=body_len * 0.45,
            )
            back_spec.notes = (
                f"centre-back {pleats.kind.replace('_', ' ')} pleat for movement ease; "
                f"fold and baste at the yoke before assembling; " + (back_spec.notes or "")
            )

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0

    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    chest = measurements.chest_cm if measurements.chest_cm is not None else (measurements.hip_cm - 4.0)
    shoulder = measurements.shoulder_width_cm if measurements.shoulder_width_cm is not None else (chest / 4 + 7.5)
    arm_length = measurements.arm_length_cm if measurements.arm_length_cm is not None else 60.0

    # Generate a single chest pocket natively when either pocket detail is present.
    # Both "chest_pocket" and "patch_pockets" refer to the same physical piece on
    # a shirt — generate exactly once to avoid duplicate pieces from the LLM fallback.
    if "chest_pocket" in details or "patch_pockets" in details:
        pocket_spec = _make_shirt_pocket(chest, measurements.seam_allowance_cm, shape=_pocket_shape(details))
        pocket_w = max(p.x for p in pocket_spec.outline)
        p_elems, p_dict = _serialise_piece(pocket_spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(p_elems)
        if p_dict:
            all_pieces.append(p_dict)

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "garmentLength": measurements.length_cm,
            "bust": chest,
            "shoulder": shoulder,
            "sleeveLength": arm_length,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


# Cargo / bellows / flap pocket synonyms the trouser block builds natively (Cargo Pocket
# + Cargo Pocket Flap). Any of these maps to the one native pair so the LLM fallback does
# not add a duplicate bag + flap. Kept in sync with _TROUSER_DETAILS in llm_fallback.py.
_CARGO_POCKET_TOKENS = (
    "cargo_pocket", "cargo_pockets", "cargo",
    "bellows_pocket", "bellows_pockets",
    "flap_pocket", "flap_pockets", "pocket_flap",
    "patch_pocket_flap",  # a flapped patch pocket on trousers == a cargo pocket
    "utility_pocket", "utility_pockets",
    "cargo_flat", "flat_cargo", "cargo_gusset", "gusset_cargo",  # cargo style variants
)


def _generate_trousers_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    details = features.details if features.details else []

    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "straight": "regular", "tapered": "slim",   "slim": "slim",
        "skinny":   "skinny",  "cigarette": "cigarette", "fitted": "fitted",
        "regular":  "regular", "relaxed": "relaxed", "wide_leg": "wide_leg",
        "flared":   "flared",  "bootcut": "bootcut", "palazzo": "palazzo",
        "jogger":   "jogger",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "regular")

    rise_style = "mid_rise"
    for d in details:
        if d in ("low_rise", "mid_rise", "high_rise", "ultra_high_rise"):
            rise_style = d
            break

    _LENGTH_MAP: dict[str, str] = {
        "full_length": "full_length", "ankle": "ankle",    "cropped": "ankle",
        "capri":       "capri",       "bermuda": "bermuda", "shorts": "shorts",
        "micro":       "shorts",      "short": "shorts",    "mid_thigh": "bermuda",
        "knee":        "bermuda",
    }
    length_category = _LENGTH_MAP.get(features.length_category or "", "full_length")

    _CLOSURE_MAP: dict[str, str] = {
        "center_back_zip": "zip_fly",      "side_zip": "side_zip",
        "center_front_zip": "zip_fly",
        "button_fly":      "button_fly",   "hook_and_eye": "zip_fly",
        "button_front":    "button_fly",
        "none":            "elastic_waist",
    }
    closure_obj = features.closure
    raw_closure = closure_obj.type if closure_obj and hasattr(closure_obj, "type") else "none"
    closure_type = _CLOSURE_MAP.get(raw_closure, "zip_fly")
    if features.waistband and hasattr(features.waistband, "type") and features.waistband.type == "elastic":
        closure_type = "elastic_waist"

    # Cargo pocket style: pleated bellows (default), separate gusset, or a flat patch.
    if any(d in details for d in ("cargo_flat", "flat_cargo")):
        cargo_style = "flat"
    elif any(d in details for d in ("cargo_gusset", "gusset_cargo")):
        cargo_style = "gusset"
    else:
        cargo_style = "bellows"

    base = build_trousers_block(
        measurements,
        fit_style=fit_style,
        rise_style=rise_style,
        length_category=length_category,
        closure_type=closure_type,
        has_fly_shield="fly_shield" in details,
        has_front_pockets="side_pockets" in details or "patch_pockets" in details,
        has_back_pockets="welt_pockets" in details or "patch_pockets" in details,
        has_cargo_pocket=any(d in details for d in _CARGO_POCKET_TOKENS),
        cargo_style=cargo_style,
        cargo_flap_shape=_pocket_shape(details),
        has_cuff_band="cuffs" in details,
        has_ankle_elastic="elastic_waist" in details or fit_style == "jogger",
        has_belt_loops="belt_loops" in details,
    )

    # Front-waist pleats (classic pleated trousers): replace the front waist dart
    # with pleats near the crease, adding fullness that releases by the hip line.
    pleats = _resolve_pleats(features, default_placement="front_waist", waist_cm=measurements.waist_cm)
    if pleats is not None and pleats.placement in ("front_waist", "all_around", "center_front"):
        front_spec = base.get("front")
        if front_spec is not None:
            front_spec.darts = []  # the pleat takes up the dart's waist intake
            wh = measurements.waist_to_hip_cm
            # outline[0] is the CF-at-waist vertex; the crotch curve dips further
            # left lower down, so use the waist vertex (not the global min x) to
            # keep the pleat between CF and the side seam.
            cf_x = front_spec.outline[0].x
            n_pleats = min(pleats.count, 2)  # 1–2 pleats per front leg
            total = pleat_unit_allowance(pleats.kind, pleats.depth) * n_pleats
            apply_pleats(
                front_spec, insert_x=cf_x + 2.0, count=n_pleats, depth=pleats.depth,
                kind=pleats.kind, y_top=0.0, release_y=wh, max_y=wh * 0.5,
                mark_region=(cf_x + 2.0, cf_x + 2.0 + total),
            )
            front_spec.notes = (
                f"{n_pleats} front {pleats.kind.replace('_', ' ')} pleat(s) at the waist near the "
                f"crease, released to the hip; fold to the placement line before attaching the "
                f"waistband; " + (front_spec.notes or "")
            )

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0

    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    wb_elems, wb_piece = _make_waistband(features, measurements, offset_x=cursor_x, offset_y=2.0)
    all_elements.extend(wb_elems)
    if wb_piece:
        all_pieces.append(wb_piece)

    inseam = measurements.inseam_cm if measurements.inseam_cm is not None else 76.0

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "waistToHip": measurements.waist_to_hip_cm,
            "garmentLength": measurements.length_cm,
            "inseam": inseam,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _generate_dress_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    details = features.details if features.details else []

    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "shift": "shift", "sheath": "sheath", "a_line": "a_line",
        "fit_and_flare": "fit_and_flare", "wrap": "wrap",
        "bodycon": "bodycon", "empire": "empire",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "a_line")

    _LENGTH_MAP: dict[str, str] = {
        "mini": "mini", "above_knee": "above_knee", "knee": "knee",
        "midi": "midi", "maxi": "maxi",
    }
    length_category = _LENGTH_MAP.get(features.length_category or "", "midi")

    _CLOSURE_MAP: dict[str, str] = {
        "center_back_zip": "center_back_zip",
        "center_front_zip": "side_zip",
        "side_zip":        "side_zip",
        "hook_and_eye":    "hook_and_eye",
        "button_fly":      "hook_and_eye",
        "button_front":    "hook_and_eye",
        "snap_front":      "hook_and_eye",
        "none":            "none",
    }
    closure_obj = features.closure
    raw_closure = closure_obj.type if closure_obj and hasattr(closure_obj, "type") else "none"
    closure_type = _CLOSURE_MAP.get(raw_closure, "center_back_zip")

    construction = _resolve_construction(features)

    base = build_dress_block(
        measurements,
        fit_style=fit_style,
        length_category=length_category,
        sleeve_length=features.sleeve_length or "sleeveless",
        neckline=features.neckline or "round",
        closure_type=closure_type,
        has_collar="collar" in details,
        has_sash=any(d in details for d in ("tie_back", "sash", "belt")),
        has_pockets=any(d in details for d in ("side_pockets", "patch_pockets")),
        has_lining="lining_visible" in details,
        strap_style=construction.strap_style,
        back_coverage=construction.back_coverage,
        front_opening=construction.front_opening,
    )

    # Honour explicit dart-count overrides from the vision analysis
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0 and "back_bodice" in base:
            base["back_bodice"].darts = []

    # Pleats in the dress skirt portion: the Front/Back Skirt pieces have a waist
    # origin (y=0) so they pleat exactly like a stand-alone skirt.
    pleats = _resolve_pleats(features, default_placement="skirt", waist_cm=measurements.waist_cm)
    if pleats is not None:
        for key in ("front_skirt", "back_skirt"):
            spec = base.get(key)
            if spec is None:
                continue
            spec.darts = []
            orig_w = max(p.x for p in spec.outline)
            total = pleat_unit_allowance(pleats.kind, pleats.depth) * pleats.count
            margin = max(2.0, total * 0.08)
            apply_pleats(
                spec, insert_x=0.0, count=pleats.count, depth=pleats.depth,
                kind=pleats.kind, y_top=0.0, release_y=None,
                mark_region=(margin, orig_w + total - margin),
            )
            spec.notes = (
                f"{pleats.count} {pleats.kind.replace('_', ' ')} pleats per panel; fold to the "
                f"placement line and baste across the waist before joining to the bodice; "
                + (spec.notes or "")
            )

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0

    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    bust = measurements.chest_cm if measurements.chest_cm is not None else (measurements.hip_cm - 4.0)

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "waistToHip": measurements.waist_to_hip_cm,
            "garmentLength": measurements.length_cm,
            "bust": bust,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _generate_jacket_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    details = features.details if features.details else []

    # 1. Silhouette → fit_style
    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "fitted":    "fitted",
        "slim":      "slim",
        "regular":   "regular",
        "relaxed":   "relaxed",
        "boxy":      "boxy",
        "oversized": "oversized",
        "moto":      "moto",
        "bomber":    "bomber",
        "military":  "military",
        "denim":     "denim",
        "anorak":    "anorak",
        "varsity":   "varsity",
        # legacy / mis-labelled silhouettes from old vocab
        "cropped":   "boxy",
        "longline":  "regular",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "regular")

    # 2. Length category
    _LENGTH_MAP: dict[str, str] = {
        "waist_length": "waist_length",
        "cropped":      "cropped",
        "hip_length":   "hip_length",
        "below_hip":    "below_hip",
        "knee":         "knee",
    }
    length_category = _LENGTH_MAP.get(features.length_category or "", "hip_length")

    # 3. Sleeve length — fall back to "long" (jackets rarely sleeveless)
    sleeve_length = features.sleeve_length or "long"

    # 4. Closure type
    _CLOSURE_MAP: dict[str, str] = {
        "center_back_zip": "zip",
        "center_front_zip": "zip",
        "side_zip":        "zip",
        "button_fly":      "button_front",
        "button_front":    "button_front",
        "snap_front":      "button_front",
        "double_breasted": "button_front",
        "hook_and_eye":    "button_front",
        "none":            "none",
    }
    closure_obj = features.closure
    raw_closure = closure_obj.type if closure_obj and hasattr(closure_obj, "type") else "none"
    closure_type = _CLOSURE_MAP.get(raw_closure, "button_front")

    # 5. Collar type (scanned from details list; first match wins)
    _COLLAR_DETAIL_MAP: dict[str, str] = {
        "notch_lapel":  "notch_lapel",
        "peak_lapel":   "peak_lapel",
        "shawl_collar": "shawl_collar",
        "band_collar":  "band_collar",
        "no_collar":    "no_collar",
    }
    collar_type = "notch_lapel"
    for d in details:
        if d in _COLLAR_DETAIL_MAP:
            collar_type = _COLLAR_DETAIL_MAP[d]
            break

    # 6. Breast style
    breast_style = "double_breasted" if "double_breasted" in details else "single_breasted"

    # 7. Detail flags
    has_yoke          = any(d in details for d in ("back_yoke", "yoke", "western_yoke"))
    has_collar        = "collar" in details or collar_type != "no_collar"
    has_facing        = (
        any(d in details for d in ("lapels", "facing", "lining_visible",
                                    "notch_lapel", "peak_lapel", "shawl_collar",
                                    "single_breasted", "double_breasted"))
        or closure_type == "button_front"
    )
    has_patch_pockets = "patch_pockets" in details
    has_welt_pockets  = "welt_pockets" in details
    has_cuff_band     = (
        any(d in details for d in ("cuff_band", "ribbed_cuffs", "knit_cuffs"))
        or fit_style in ("bomber", "varsity")
    )
    has_hem_band      = (
        any(d in details for d in ("hem_band", "ribbed_hem", "knit_hem"))
        or fit_style in ("bomber", "varsity")
    )
    has_hood          = "hood" in details
    has_lining        = "lining_visible" in details
    # Tailored two-piece sleeve auto-enabled for close-fitting silhouettes
    has_two_piece_sleeve = (
        any(d in details for d in ("two_piece_sleeve", "tailored_sleeve"))
        or fit_style in ("fitted", "slim", "moto", "military")
    )
    has_cuff = any(d in details for d in ("cuffs", "button_cuff", "snap_cuff", "woven_cuff"))
    has_breast_pocket   = any(d in details for d in ("breast_pocket", "chest_pocket", "chest_welt"))
    has_in_seam_pockets = any(d in details for d in ("in_seam_pockets", "slash_pockets", "side_pockets"))
    has_sleeve_placket  = any(d in details for d in ("sleeve_placket", "cuff_vent"))
    has_belt            = any(d in details for d in ("belt", "belt_strap", "self_belt"))
    has_epaulets        = any(d in details for d in ("epaulets", "epaulet_tab", "shoulder_tab"))

    # 8. Build pieces
    base = build_jacket_block(
        measurements,
        fit_style=fit_style,
        sleeve_length=sleeve_length,
        length_category=length_category,
        closure_type=closure_type,
        collar_type=collar_type,
        breast_style=breast_style,
        has_yoke=has_yoke,
        has_collar=has_collar,
        has_facing=has_facing,
        has_patch_pockets=has_patch_pockets,
        has_welt_pockets=has_welt_pockets,
        has_cuff_band=has_cuff_band,
        has_hem_band=has_hem_band,
        has_hood=has_hood,
        has_lining=has_lining,
        has_two_piece_sleeve=has_two_piece_sleeve,
        has_cuff=has_cuff,
        has_breast_pocket=has_breast_pocket,
        has_in_seam_pockets=has_in_seam_pockets,
        has_sleeve_placket=has_sleeve_placket,
        has_belt=has_belt,
        has_epaulets=has_epaulets,
        pocket_shape=_pocket_shape(details),
    )

    # Honour explicit dart-count overrides from vision analysis
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0:
            for key in ("back_bodice", "back_yoke", "back_panel"):
                if key in base:
                    base[key].darts = []

    # Centre-back action / inverted pleat (utility, anorak, trench) when detected.
    pleats = _resolve_pleats(features, default_placement="center_back", waist_cm=measurements.waist_cm)
    if pleats is not None and pleats.placement in ("center_back", "back_waist", "all_around", "skirt"):
        for key in ("back_bodice", "back_panel"):
            back_spec = base.get(key)
            if back_spec is not None:
                body_len = max(p.y for p in back_spec.outline)
                apply_pleats(
                    back_spec, insert_x=1.0, count=1, depth=pleats.depth,
                    kind=pleats.kind, y_top=0.0, release_y=body_len * 0.5,
                )
                back_spec.notes = (
                    f"centre-back {pleats.kind.replace('_', ' ')} action pleat for movement; "
                    f"fold and baste at the top before assembling; " + (back_spec.notes or "")
                )
                break

    # 7. Serialise (same boilerplate as every other garment generator)
    all_elements: list[dict] = []
    all_pieces:   list[dict] = []
    gap      = 5.0
    cursor_x = 2.0

    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    chest      = measurements.chest_cm if measurements.chest_cm is not None else (measurements.hip_cm - 4.0)
    shoulder   = measurements.shoulder_width_cm if measurements.shoulder_width_cm is not None else (chest / 4 + 7.5)
    arm_length = measurements.arm_length_cm if measurements.arm_length_cm is not None else 60.0

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist":       measurements.waist_cm,
            "hip":         measurements.hip_cm,
            "garmentLength": measurements.length_cm,
            "bust":        chest,
            "shoulder":    shoulder,
            "sleeveLength": arm_length,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _resolve_vest_finishes(features: GarmentFeatures) -> tuple[tuple[str, ...], float, bool, tuple[str, ...], int, float, bool]:
    """Merge the structured vest fields with loose detail tokens into builder kwargs.

    Returns (binding_edges, binding_width, binding_contrast, facings,
             welt_count, welt_width, welt_besom). Detail-token fallbacks let an analysis
    that only emitted strings (e.g. "neckline_binding", "welt_pockets") still drive the
    geometry, while the structured fields take precedence when present.
    """
    details = features.details or []

    # Binding
    binding_edges: list[str] = []
    binding_width = 1.0
    binding_contrast = True
    if features.binding is not None and features.binding.edges:
        binding_edges = list(features.binding.edges)
        binding_width = features.binding.width_cm
        binding_contrast = features.binding.contrast
    else:
        if any(d in details for d in ("neckline_binding", "contrast_binding", "binding", "piping")):
            binding_edges.append("neckline")
        if "armhole_binding" in details:
            binding_edges.append("armhole")
        if "hem_binding" in details:
            binding_edges.append("hem")

    # Facings
    facings: list[str] = list(features.facings or [])
    if "armhole_facing" in details and "armhole" not in facings:
        facings.append("armhole")
    if "hem_facing" in details and "hem" not in facings:
        facings.append("hem")
    if "neckline_facing" in details and "neckline" not in facings:
        facings.append("neckline")

    # An edge is EITHER bound (visible lip) OR faced (clean inside finish) — when
    # the analysis contradicts itself and lists both, the facing wins: it is the
    # conservative finish that adds no visible design element the photo may lack.
    binding_edges = [e for e in binding_edges if e not in set(facings)]

    # Welt pockets
    welt_count = 0
    welt_width = 14.0
    welt_besom = False
    if features.welt_pockets:
        welt_count = sum(max(1, wp.count) for wp in features.welt_pockets)
        welt_width = features.welt_pockets[0].width_cm
        welt_besom = features.welt_pockets[0].besom
    elif "welt_pockets" in details or "besom_pockets" in details:
        welt_count = 2  # a symmetric pair is the common case
        welt_besom = "besom_pockets" in details

    return (
        tuple(binding_edges), binding_width, binding_contrast,
        tuple(facings), welt_count, welt_width, welt_besom,
    )


def _resolve_asymmetry(features: GarmentFeatures) -> tuple[str, str, float, float]:
    """Return (front_style, wrap_side, overlap_cm, closure_drop_frac) from the structured
    asymmetry field, with a detail-token fallback (``asymmetric_wrap`` / ``wrap_front``)."""
    a = features.asymmetry
    if a is not None and a.front_style == "asymmetric_wrap":
        return a.front_style, a.wrap_side, a.overlap_cm, a.closure_drop_frac
    details = features.details or []
    if any(d in details for d in ("asymmetric_wrap", "asymmetric_front", "wrap_front", "diagonal_closure")):
        return "asymmetric_wrap", "right", 12.0, 1.0
    return "symmetric", "right", 12.0, 1.0


def _resolve_collar(features: GarmentFeatures) -> str:
    """Return the vest collar style from the neckline or detail tokens (else 'none')."""
    neckline = (features.neckline or "").lower()
    if neckline in ("mandarin", "band", "stand", "mandarin_collar"):
        return "mandarin"
    details = features.details or []
    if any(d in details for d in ("mandarin_collar", "band_collar", "stand_collar", "mandarin", "collar")):
        return "mandarin"
    return "none"


def _generate_vest_pattern(
    features: GarmentFeatures, measurements: Measurements, shape_mode: ShapeMode = "modifiers",
) -> dict:
    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "slim": "slim", "fitted": "fitted", "regular": "regular",
        "relaxed": "relaxed", "boxy": "boxy", "oversized": "oversized",
        "athletic": "athletic", "longline": "longline",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "boxy")

    ease_map = {
        "slim": -2.0, "fitted": -2.0, "regular": 0.0, "relaxed": 2.0,
        "boxy": 4.0, "oversized": 6.0, "athletic": -1.0, "longline": 0.0,
    }
    ease_extra = ease_map.get(fit_style, 4.0)

    (binding_edges, binding_width, binding_contrast,
     facings, welt_count, welt_width, welt_besom) = _resolve_vest_finishes(features)
    front_style, wrap_side, overlap_cm, closure_drop_frac = _resolve_asymmetry(features)
    collar_style = _resolve_collar(features)

    base = build_vest_block(
        measurements,
        fit_style=fit_style,
        neckline=features.neckline or "notched_v",
        chest_ease_extra=ease_extra,
        binding_edges=binding_edges,
        binding_width=binding_width,
        binding_contrast=binding_contrast,
        facings=facings,
        welt_count=welt_count,
        welt_width=welt_width,
        welt_besom=welt_besom,
        bake_shape=(shape_mode == "fit_params" and features.shape is not None),
        front_style=front_style,
        wrap_side=wrap_side,
        overlap_cm=overlap_cm,
        closure_drop_frac=closure_drop_frac,
        collar_style=collar_style,
    )

    # Honour explicit dart-count overrides from the vision analysis
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0 and "back_bodice" in base:
            base["back_bodice"].darts = []

    # Shape layer (modifiers / warp); fit_params was baked into the block above.
    base = apply_shape(base, features, measurements, mode=shape_mode)

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0

    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    chest = measurements.chest_cm if measurements.chest_cm is not None else (measurements.hip_cm - 4.0)
    shoulder = measurements.shoulder_width_cm if measurements.shoulder_width_cm is not None else (chest / 4 + 7.5)

    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "garmentLength": measurements.length_cm,
            "bust": chest,
            "shoulder": shoulder,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _generate_bodice_pattern(
    features: GarmentFeatures, measurements: Measurements, shape_mode: ShapeMode = "modifiers",
) -> dict:
    """A fitted sleeveless bodice block — reuses the vest block (with shoulder seams) so the
    shared shape layer is exercised on a second garment. Makes GarmentType.BODICE real
    (previously routed to the measurements-only placeholder)."""
    _SILHOUETTE_TO_FIT: dict[str, str] = {
        "fitted": "fitted", "slim": "slim", "boned": "fitted",
        "relaxed": "relaxed", "wrap": "relaxed", "regular": "regular",
    }
    fit_style = _SILHOUETTE_TO_FIT.get(features.silhouette or "", "fitted")

    (binding_edges, binding_width, binding_contrast,
     facings, welt_count, welt_width, welt_besom) = _resolve_vest_finishes(features)
    front_style, wrap_side, overlap_cm, closure_drop_frac = _resolve_asymmetry(features)

    base = build_vest_block(
        measurements,
        fit_style=fit_style,
        neckline=features.neckline or "v_neck",
        chest_ease_extra=0.0,
        binding_edges=binding_edges,
        binding_width=binding_width,
        binding_contrast=binding_contrast,
        facings=facings,
        welt_count=welt_count,
        welt_width=welt_width,
        welt_besom=welt_besom,
        bake_shape=(shape_mode == "fit_params" and features.shape is not None),
        front_style=front_style,
        wrap_side=wrap_side,
        overlap_cm=overlap_cm,
        closure_drop_frac=closure_drop_frac,
        collar_style=_resolve_collar(features),
    )

    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0 and "back_bodice" in base:
            base["back_bodice"].darts = []

    base = apply_shape(base, features, measurements, mode=shape_mode)

    all_elements: list[dict] = []
    all_pieces: list[dict] = []
    gap = 5.0
    cursor_x = 2.0
    for spec in base.values():
        max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += max_x + gap

    chest = measurements.chest_cm if measurements.chest_cm is not None else (measurements.hip_cm - 4.0)
    return {
        "version": 1,
        "elements": all_elements,
        "pieces": all_pieces,
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "garmentLength": measurements.length_cm,
            "bust": chest,
        },
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _generate_placeholder_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    """Return an empty canvas with measurements pre-loaded for unsupported garment types."""
    return {
        "version": 1,
        "elements": [],
        "pieces": [],
        "measurements": {
            "waist": measurements.waist_cm,
            "hip": measurements.hip_cm,
            "waistToHip": measurements.waist_to_hip_cm,
            "garmentLength": measurements.length_cm,
        },
        "notice": (
            f"Pattern generation for '{features.garment_type.value}' is not yet automated. "
            "Your measurements have been loaded — use the canvas tools to draft the pattern manually."
        ),
    }


# ── Novel-piece appender ──────────────────────────────────────────────────────

def _edge_run_lengths(psnap: dict) -> dict[str, float]:
    """Per attachment label (hem/waist/neckline/…), the longest per-piece run of
    outline edges carrying that seamLabel — real numbers the LLM fallback uses to
    size a novel piece's attachment edge."""
    from app.patterns.novel_validation import ATTACHMENT_LABELS

    outline_ids: set[str] = set()
    for p in psnap.get("pieces", []):
        outline_ids.update(p["elementIds"])

    runs: dict[str, dict[str, float]] = {}
    for elem in psnap.get("elements", []):
        if elem["id"] not in outline_ids or elem.get("isFold"):
            continue
        label = elem.get("seamLabel", "")
        if label not in ATTACHMENT_LABELS:
            continue
        by_piece = runs.setdefault(label, {})
        by_piece[elem["pieceId"]] = by_piece.get(elem["pieceId"], 0.0) + _edge_length(elem)

    return {label: max(by_piece.values()) for label, by_piece in runs.items()}


def _append_specs(psnap: dict, specs: list) -> dict:
    """Serialise extra PieceSpecs to the right of the existing layout and
    recompute connections so labelled attachment edges are sewn into assembly."""
    if not specs:
        return psnap

    # Find the rightmost x already on the canvas to position new pieces beside it
    max_x = 2.0
    for elem in psnap.get("elements", []):
        for key in ("start", "end"):
            pt = elem.get(key)
            if pt:
                max_x = max(max_x, pt.get("x", 0.0))

    gap = 5.0
    cursor_x = max_x + gap

    all_elements = list(psnap.get("elements", []))
    all_pieces = list(psnap.get("pieces", []))

    for spec in specs:
        spec_max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += spec_max_x + gap

    return {
        **psnap,
        "elements": all_elements,
        "pieces": all_pieces,
        "connections": _compute_connections(all_elements, all_pieces),
    }


def _append_vision_pieces(
    psnap: dict,
    features: GarmentFeatures,
    measurements: Measurements,
) -> tuple[dict, set[str]]:
    """Patternize vision-detected contours into pieces. Returns the updated psnap
    plus the detail tokens the contours covered, so the LLM fallback does not
    generate a second piece for the same physical feature."""
    # getattr: the legacy SkirtFeatures model has no piece_contours field
    if not getattr(features, "piece_contours", None):
        return psnap, set()
    from app.patterns.vision_contours import generate_vision_pieces

    existing_names = {p.get("name", "") for p in psnap.get("pieces", [])}
    specs = generate_vision_pieces(features, measurements, existing_names=existing_names)
    handled = {spec.detail for spec in specs if spec.detail}
    return _append_specs(psnap, specs), handled


def _append_novel_pieces(
    psnap: dict,
    features: GarmentFeatures,
    measurements: Measurements,
    exclude: set[str] | frozenset = frozenset(),
) -> dict:
    """Detect unsupported details, generate their pieces via LLM / learned store,
    and append them to the right of the existing pattern layout. ``exclude`` lists
    details already covered elsewhere (e.g. by a vision contour)."""
    unsupported = [d for d in detect_unsupported_details(features) if d not in exclude]
    if not unsupported:
        return psnap

    extra_specs = generate_novel_pieces(
        unsupported, features, measurements, edge_runs=_edge_run_lengths(psnap)
    )
    return _append_specs(psnap, extra_specs)


# ── Public API ────────────────────────────────────────────────────────────────

def _generate_base(
    features: GarmentFeatures,
    measurements: Measurements,
    shape_mode: ShapeMode = "modifiers",
) -> dict | None:
    """Dispatch to the native per-garment generator, or None when the garment type
    has no dedicated block (the caller then tries composition, then the placeholder).
    Also called by compositions.py to draft each component of a composed garment."""
    if features.garment_type == GarmentType.SKIRT:
        return _generate_skirt_pattern(features, measurements)
    if features.garment_type in (GarmentType.SHIRT, GarmentType.BLOUSE):
        return _generate_shirt_pattern(features, measurements)
    if features.garment_type in (GarmentType.PANTS, GarmentType.TROUSERS):
        return _generate_trousers_pattern(features, measurements)
    if features.garment_type == GarmentType.DRESS:
        return _generate_dress_pattern(features, measurements)
    if features.garment_type in (GarmentType.JACKET, GarmentType.BLAZER):
        return _generate_jacket_pattern(features, measurements)
    if features.garment_type == GarmentType.VEST:
        return _generate_vest_pattern(features, measurements, shape_mode)
    if features.garment_type == GarmentType.BODICE:
        return _generate_bodice_pattern(features, measurements, shape_mode)
    return None


def generate_pattern(
    features: GarmentFeatures,
    measurements: Measurements,
    shape_mode: ShapeMode = "modifiers",
) -> dict:
    """Return a .psnap JSON-compatible dict for the given garment features + measurements.

    ``shape_mode`` selects the silhouette-generation strategy for shape-aware garments
    (vest / bodice): "modifiers" (default), "warp", or "fit_params".

    Garment types without a native block are composed from existing builders
    (compositions.py: static plans, then the LLM planner); the measurements-only
    placeholder is returned only when composition genuinely fails.
    """
    psnap = _generate_base(features, measurements, shape_mode)
    if psnap is None:
        from app.patterns.compositions import compose_pattern

        psnap = compose_pattern(features, measurements, shape_mode)
    if psnap is None:
        psnap = _generate_placeholder_pattern(features, measurements)

    # Vision contours first — a detail covered by a traced contour must not also
    # get an LLM-guessed piece for the same physical feature.
    psnap, handled = _append_vision_pieces(psnap, features, measurements)
    return _append_novel_pieces(psnap, features, measurements, exclude=handled)
