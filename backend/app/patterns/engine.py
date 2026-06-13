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

import uuid

from app.models.features import GarmentFeatures, GarmentType
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.llm_fallback import detect_unsupported_details, generate_novel_pieces
from app.patterns.modifiers import apply_feature_modifiers, apply_silhouette
from app.patterns.dresses import build_dress_block
from app.patterns.jackets import build_jacket_block
from app.patterns.shirts import build_shirt_block
from app.patterns.skirts import DartSpec, PieceSpec, build_skirt_block, build_straight_skirt_block
from app.patterns.trousers import build_trousers_block


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
        "notes": spec.notes,
    }

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

def _compute_connections(all_elements: list[dict], all_pieces: list[dict]) -> list[dict]:
    """Return pairs of edges that share the same non-empty seamLabel across different pieces."""
    from itertools import combinations

    piece_by_id = {p["id"]: p for p in all_pieces}
    # Group outline elements by seamLabel (skip empty / fold lines)
    label_groups: dict[str, list[dict]] = {}
    outline_ids: set[str] = set()
    for p in all_pieces:
        for eid in p["elementIds"]:
            outline_ids.add(eid)

    for elem in all_elements:
        if elem["id"] not in outline_ids:
            continue
        label = elem.get("seamLabel", "")
        if not label or elem.get("isFold"):
            continue
        label_groups.setdefault(label, []).append(elem)

    connections: list[dict] = []
    for label, edges in label_groups.items():
        # Only pair edges that belong to different pieces
        for a, b in combinations(edges, 2):
            if a.get("pieceId") != b.get("pieceId"):
                connections.append({
                    "label": label,
                    "from": {"pieceId": a["pieceId"], "edgeId": a["id"]},
                    "to":   {"pieceId": b["pieceId"], "edgeId": b["id"]},
                })
    return connections


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
    )

    # Honour explicit AI dart-count overrides (e.g. vision returns darts.front == 0)
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front" in pieces:
            pieces["front"].darts = []
        if features.darts.back == 0 and "back" in pieces:
            pieces["back"].darts = []

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


def _make_shirt_pocket(chest_cm: float, sa: float) -> PieceSpec:
    """Generate a single chest patch pocket piece sized from chest measurement."""
    pocket_w = max(10.0, chest_cm * 0.13)
    pocket_h = max(12.0, chest_cm * 0.155)
    spec = PieceSpec(
        name="Chest Patch Pocket",
        outline=[
            Point(0.0, 0.0),
            Point(pocket_w, 0.0),
            Point(pocket_w, pocket_h),
            Point(0.0, pocket_h),
        ],
        darts=[],
        grain_start=Point(pocket_w * 0.2, pocket_h / 2),
        grain_end=Point(pocket_w * 0.8, pocket_h / 2),
        cut_qty=1,
        on_fold=False,
        seam_allowance=sa,
    )
    return spec


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
        pocket_spec = _make_shirt_pocket(chest, measurements.seam_allowance_cm)
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

    base = build_trousers_block(
        measurements,
        fit_style=fit_style,
        rise_style=rise_style,
        length_category=length_category,
        closure_type=closure_type,
        has_fly_shield="fly_shield" in details,
        has_front_pockets="side_pockets" in details or "patch_pockets" in details,
        has_back_pockets="welt_pockets" in details or "patch_pockets" in details,
        has_cargo_pocket="cargo_pocket" in details,
        has_cuff_band="cuffs" in details,
        has_ankle_elastic="elastic_waist" in details or fit_style == "jogger",
        has_belt_loops="belt_loops" in details,
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
    )

    # Honour explicit dart-count overrides from the vision analysis
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0 and "back_bodice" in base:
            base["back_bodice"].darts = []

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
    )

    # Honour explicit dart-count overrides from vision analysis
    if hasattr(features, "darts") and features.darts is not None:
        if features.darts.front == 0 and "front_bodice" in base:
            base["front_bodice"].darts = []
        if features.darts.back == 0:
            for key in ("back_bodice", "back_yoke", "back_panel"):
                if key in base:
                    base[key].darts = []

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

def _append_novel_pieces(
    psnap: dict,
    features: GarmentFeatures,
    measurements: Measurements,
) -> dict:
    """Detect unsupported details, generate their pieces via LLM / learned store,
    and append them to the right of the existing pattern layout."""
    unsupported = detect_unsupported_details(features)
    if not unsupported:
        return psnap

    extra_specs = generate_novel_pieces(unsupported, features, measurements)
    if not extra_specs:
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

    for spec in extra_specs:
        spec_max_x = max(p.x for p in spec.outline)
        elems, piece_dict = _serialise_piece(spec, offset_x=cursor_x, offset_y=2.0)
        all_elements.extend(elems)
        if piece_dict:
            all_pieces.append(piece_dict)
        cursor_x += spec_max_x + gap

    return {**psnap, "elements": all_elements, "pieces": all_pieces}


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pattern(features: GarmentFeatures, measurements: Measurements) -> dict:
    """Return a .psnap JSON-compatible dict for the given garment features + measurements."""
    if features.garment_type == GarmentType.SKIRT:
        psnap = _generate_skirt_pattern(features, measurements)
    elif features.garment_type in (GarmentType.SHIRT, GarmentType.BLOUSE):
        psnap = _generate_shirt_pattern(features, measurements)
    elif features.garment_type in (GarmentType.PANTS, GarmentType.TROUSERS):
        psnap = _generate_trousers_pattern(features, measurements)
    elif features.garment_type == GarmentType.DRESS:
        psnap = _generate_dress_pattern(features, measurements)
    elif features.garment_type in (GarmentType.JACKET, GarmentType.BLAZER):
        psnap = _generate_jacket_pattern(features, measurements)
    else:
        psnap = _generate_placeholder_pattern(features, measurements)

    return _append_novel_pieces(psnap, features, measurements)
