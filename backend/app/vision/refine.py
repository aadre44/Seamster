"""Photo-driven refine pass: the vision LLM edits the engine's drafted outlines.

The parametric engine drafts measurement-true pieces, but their SHAPES are only
as garment-specific as the vocabulary allows. This pass closes the gap the same
way a pattern maker would (and the way the blueVest reference correction was
made by hand — harness/blueVestCorrected.svg): show the model the photo AND the
drafted flat pieces, and let it return corrected outlines — bezier curves
allowed — only for the pieces whose shape disagrees with the photo.

Flow (triggered by an explicit "Refine shapes from photo" button, POST /api/refine):

  1. serialize the psnap pieces into a compact per-piece JSON (cm, local coords,
     per-edge seam labels, cps for curved edges),
  2. one vision call (photo + pieces JSON); one repair re-prompt on validation
     failure; on the final attempt valid pieces are kept and invalid dropped,
  3. every returned piece passes hard guards (name must match, seam-label set
     preserved, bbox within REFINE_MAX_DELTA of the draft, sane control points,
     fold edge intact) plus the shared tier-3 geometry validation,
  4. accepted outlines replace the piece's geometry IN PLACE — same piece id,
     same canvas position, interior marks untouched — and connections are
     recomputed. Refined pieces carry source="vision" so the canvas styles them
     as drafts.

The failure mode is always "no change": junk responses reject piece-by-piece and
the original psnap comes back untouched.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.debug_trace import add_event, begin_refine, trace_refine
from app.llm import acomplete_with_retry, get_provider, parse_json_response
from app.models.features import GarmentType
from app.models.measurements import Measurements
from app.patterns.engine import _compute_connections, _serialise_piece
from app.patterns.finishings import path_length
from app.patterns.geometry import CurveSegment, Point
from app.patterns.novel_validation import validate_spec
from app.patterns.skirts import PieceSpec

logger = logging.getLogger(__name__)

# ── Tunable guards ─────────────────────────────────────────────────────────────
#: Refined piece bbox width/height must stay within this fraction of the draft.
REFINE_MAX_DELTA = 0.30
#: Control points farther than this factor of the outline bbox are rejected.
MAX_CP_BBOX_FACTOR = 1.5
#: Vertex-count window for a replacement outline.
MIN_POINTS, MAX_POINTS = 3, 40
#: On-fold pieces: first/last vertices must stay within this fraction of the
#: bbox diagonal of their drafted positions (the fold edge is load-bearing).
FOLD_ANCHOR_TOLERANCE = 0.10
#: Structural seams must keep their drafted length or the pieces stop sewing
#: together: the summed per-label path length of these edges may drift at most
#: this fraction from the draft.
STRUCTURAL_LABELS = frozenset(
    {"shoulder", "armhole", "side_seam", "waist", "waist_seam", "inseam", "crotch"}
)
SEAM_LENGTH_TOLERANCE = 0.12
#: LLM attempts: one initial call plus one repair re-prompt.
_MAX_ATTEMPTS = 2
#: Response budget — a 6-piece garment with bezier outlines easily exceeds 4k
#: tokens, and a truncated response used to reject EVERY piece (silent no-change).
_MAX_RESPONSE_TOKENS = 8192
# ───────────────────────────────────────────────────────────────────────────────

_CP_KEYS = ("cp1x", "cp1y", "cp2x", "cp2y")

_REFINE_SYSTEM_PROMPT = """You are an expert garment pattern maker. You are shown \
photograph(s) of a real garment and the flat pattern pieces a parametric engine drafted \
for it, as JSON outlines (units: cm, y grows DOWNWARD, each outline closes automatically \
from its last point back to its first).

Point format: {"x", "y", "edge_label", optionally "cp1x","cp1y","cp2x","cp2y"}.
- "edge_label" names the seam on the edge LEAVING this point (to the next point).
- The cp values make the edge ARRIVING at this point (from the previous point) a cubic \
bezier: cp1 sits near the previous point, cp2 near this point. Give all four or none.

YOUR TASK: compare each drafted piece's FLAT SHAPE against the garment in the photo and \
return ONLY the pieces whose shape disagrees, each as a COMPLETE replacement outline. If \
every piece already matches the photo, return {"pieces": []}.

Editing rules:
- Keep "name" EXACTLY as given. Never add, remove, split, merge, or rename pieces.
- Every distinct edge_label on the original piece must appear on your outline too, and \
structural seams (shoulder, side_seam, armhole, waist) must keep roughly their drafted \
length so the pieces still sew together. Reshape the FREE edges — necklines, closure and \
wrap edges, hems, style lines — to match the photo, using bezier curves for edges that \
are genuinely curved.
- Coordinates stay in cm at the drafted scale: the piece's overall width and height must \
each stay within 30% of the drafted piece.
- Pieces with "on_fold": true: the closing edge (last point back to first point) lies on \
the fabric fold — keep it straight, keep the FIRST point first, and leave the first and \
last points where they are.
- 3 to 40 points per outline. Trace deliberately: use as many points and curves as the \
real silhouette needs, no more.

Respond with ONLY this JSON object, no markdown fences, no commentary:
{"pieces": [{"name": "<exact name>", "reason": "<one sentence: what disagreed with the \
photo>", "outline": [{"x": 0.0, "y": 0.0, "edge_label": "shoulder"}, ...]}]}"""


# ── psnap → compact JSON ───────────────────────────────────────────────────────

@dataclass
class _PieceCtx:
    """Everything needed to validate a replacement outline and splice it back."""
    piece_id: str
    name: str
    offset_x: float
    offset_y: float
    width: float
    height: float
    labels: frozenset[str]
    on_fold: bool
    cut_qty: int
    seam_allowance: float
    outline_ids: list[str] = field(default_factory=list)
    first_vertex: tuple[float, float] = (0.0, 0.0)   # local coords
    last_vertex: tuple[float, float] = (0.0, 0.0)
    #: Drafted per-label summed edge length (cm) for the structural-seam guard.
    label_lengths: dict[str, float] = field(default_factory=dict)


def _element_length(el: dict) -> float:
    """Arc length of one psnap outline element (line or cubic-bezier curve)."""
    start = Point(el["start"]["x"], el["start"]["y"])
    if el.get("type") == "curve":
        end = CurveSegment(
            el["end"]["x"], el["end"]["y"],
            cp1=Point(el["cp1"]["x"], el["cp1"]["y"]),
            cp2=Point(el["cp2"]["x"], el["cp2"]["y"]),
        )
    else:
        end = Point(el["end"]["x"], el["end"]["y"])
    return path_length([start, end])


def _outline_label_lengths(
    vertices: list[Point | CurveSegment], edge_labels: dict[int, str]
) -> dict[str, float]:
    """Summed path length per edge label of a replacement outline.

    Edge i runs vertex i → vertex i+1 (wrapping); a CurveSegment target makes the
    edge a cubic bezier — the same conventions as PieceSpec outlines."""
    n = len(vertices)
    sums: dict[str, float] = {}
    for i in range(n):
        label = edge_labels.get(i, "")
        if not label:
            continue
        a, b = vertices[i], vertices[(i + 1) % n]
        length = path_length([Point(a.x, a.y), b])
        sums[label] = sums.get(label, 0.0) + length
    return sums


def _pieces_to_compact(psnap: dict) -> tuple[list[dict], dict[str, _PieceCtx]]:
    """Serialize every psnap piece into the compact JSON the LLM edits.

    Uses the engine's serialization conventions: ``elementIds`` lists the outline
    elements in order; element i runs vertex i → vertex i+1; a "curve" element
    makes vertex i+1 the endpoint of a cubic bezier; ``seamLabel`` on element i
    is the label of edge i. Pieces are translated to local coordinates (bbox min
    at the origin) so the model reasons about shapes, not canvas layout.
    """
    elements = {e["id"]: e for e in psnap.get("elements", [])}
    compact: list[dict] = []
    ctx: dict[str, _PieceCtx] = {}

    for piece in psnap.get("pieces", []):
        name = piece.get("name", "")
        if not name or name in ctx:
            # The LLM addresses pieces by name — an unnamed or duplicate-named
            # piece cannot be safely targeted, so it is left out of the pass.
            continue
        elems = [elements[eid] for eid in piece.get("elementIds", []) if eid in elements]
        if len(elems) < MIN_POINTS:
            continue
        n = len(elems)
        min_x = min(e["start"]["x"] for e in elems)
        min_y = min(e["start"]["y"] for e in elems)
        max_x = max(e["start"]["x"] for e in elems)
        max_y = max(e["start"]["y"] for e in elems)

        outline_json: list[dict] = []
        for i, el in enumerate(elems):
            entry: dict = {
                "x": round(el["start"]["x"] - min_x, 1),
                "y": round(el["start"]["y"] - min_y, 1),
                "edge_label": el.get("seamLabel", "") or "",
            }
            arriving = elems[(i - 1) % n]      # the edge that ends at this vertex
            if arriving.get("type") == "curve":
                entry["cp1x"] = round(arriving["cp1"]["x"] - min_x, 1)
                entry["cp1y"] = round(arriving["cp1"]["y"] - min_y, 1)
                entry["cp2x"] = round(arriving["cp2"]["x"] - min_x, 1)
                entry["cp2y"] = round(arriving["cp2"]["y"] - min_y, 1)
            outline_json.append(entry)

        compact.append({
            "name": name,
            "cut_qty": piece.get("cutQty", 1),
            "on_fold": bool(piece.get("onFold", False)),
            "outline": outline_json,
        })
        label_lengths: dict[str, float] = {}
        for el in elems:
            label = el.get("seamLabel", "") or ""
            if label:
                label_lengths[label] = label_lengths.get(label, 0.0) + _element_length(el)

        ctx[name] = _PieceCtx(
            piece_id=piece["id"],
            name=name,
            offset_x=min_x,
            offset_y=min_y,
            width=max_x - min_x,
            height=max_y - min_y,
            labels=frozenset(l for l in (e.get("seamLabel", "") for e in elems) if l),
            on_fold=bool(piece.get("onFold", False)),
            cut_qty=piece.get("cutQty", 1),
            seam_allowance=piece.get("seamAllowance", 1.5),
            outline_ids=[e["id"] for e in elems],
            first_vertex=(elems[0]["start"]["x"] - min_x, elems[0]["start"]["y"] - min_y),
            last_vertex=(elems[-1]["start"]["x"] - min_x, elems[-1]["start"]["y"] - min_y),
            label_lengths=label_lengths,
        )

    return compact, ctx


def _salvage_pieces(text: str) -> list[dict]:
    """Recover complete piece objects from a truncated response.

    A response cut off at the token limit usually dies mid-object inside the
    ``"pieces"`` array. Scan from the array's opening bracket with a
    string-aware brace counter and json-load every complete top-level object;
    whatever parses is returned (the half-written trailing object is dropped).
    """
    key = text.find('"pieces"')
    if key < 0:
        return []
    start = text.find("[", key)
    if start < 0:
        return []

    entries: list[dict] = []
    depth = 0
    obj_start = -1
    in_string = False
    escaped = False
    for i in range(start + 1, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                try:
                    obj = json.loads(text[obj_start:i + 1])
                    if isinstance(obj, dict):
                        entries.append(obj)
                except ValueError:
                    pass
                obj_start = -1
        elif ch == "]" and depth == 0:
            break
    return entries


# ── LLM response → validated PieceSpec ─────────────────────────────────────────

def _entry_to_outline(entry_outline: list) -> tuple[list[Point | CurveSegment], dict[int, str]]:
    """One response piece's outline JSON → (vertices, edge_labels). Raises ValueError.

    Two model habits are normalized rather than rejected (mirroring tier-2's
    ``_custom_outline``): an explicit closing duplicate of the first point is
    dropped (our outlines close implicitly, and the zero-length edge it creates
    would falsely trip the self-intersection check), and control points that
    coincide with their own vertex — the model's way of marking a straight edge
    — are treated as a plain point."""
    if not isinstance(entry_outline, list):
        raise ValueError("'outline' must be an array of point objects")

    pts = [dict(p) if isinstance(p, dict) else p for p in entry_outline]
    # Drop an explicit closing duplicate; if it carried real control points they
    # describe the closing edge, which arrives at vertex 0 — move them there.
    if len(pts) > 3 and isinstance(pts[0], dict) and isinstance(pts[-1], dict):
        try:
            same = (abs(float(pts[-1]["x"]) - float(pts[0]["x"])) < 0.05
                    and abs(float(pts[-1]["y"]) - float(pts[0]["y"])) < 0.05)
        except (KeyError, TypeError, ValueError):
            same = False
        if same:
            dup = pts.pop()
            if all(k in dup and dup[k] is not None for k in _CP_KEYS) and not all(
                k in pts[0] and pts[0][k] is not None for k in _CP_KEYS
            ):
                for k in _CP_KEYS:
                    pts[0][k] = dup[k]

    if not MIN_POINTS <= len(pts) <= MAX_POINTS:
        raise ValueError(f"outline has {len(pts)} points; expected {MIN_POINTS}-{MAX_POINTS}")

    vertices: list[Point | CurveSegment] = []
    edge_labels: dict[int, str] = {}
    for i, pt in enumerate(pts):
        if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
            raise ValueError(f"outline point {i} must be an object with numeric 'x' and 'y'")
        try:
            x, y = float(pt["x"]), float(pt["y"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"outline point {i} has non-numeric coordinates") from exc
        if all(k in pt and pt[k] is not None for k in _CP_KEYS):
            try:
                cps = [float(pt[k]) for k in _CP_KEYS]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"outline point {i} has non-numeric control points") from exc
            degenerate = (abs(cps[0] - x) < 0.01 and abs(cps[1] - y) < 0.01
                          and abs(cps[2] - x) < 0.01 and abs(cps[3] - y) < 0.01)
            if degenerate:
                vertices.append(Point(x, y))
            else:
                vertices.append(CurveSegment(x, y, cp1=Point(cps[0], cps[1]), cp2=Point(cps[2], cps[3])))
        else:
            vertices.append(Point(x, y))
        label = str(pt.get("edge_label", "") or "")
        if label:
            edge_labels[i] = label
    return vertices, edge_labels


def _validate_entry(entry: dict, ctx: dict[str, _PieceCtx], measurements: Measurements) -> tuple[PieceSpec | None, list[str]]:
    """Validate one response piece against its drafted original.

    Returns (spec, []) on success or (None, problems). Every problem message is
    written to be fed straight back into the repair re-prompt."""
    name = str(entry.get("name", ""))
    if name not in ctx:
        return None, [f"unknown piece '{name}' — the pieces are: {', '.join(sorted(ctx))}"]
    c = ctx[name]
    problems: list[str] = []

    try:
        vertices, edge_labels = _entry_to_outline(entry.get("outline"))
    except ValueError as exc:
        return None, [f"{name}: {exc}"]

    # Seam-label set must survive — _compute_connections pairs edges by label.
    new_labels = frozenset(edge_labels.values())
    missing = c.labels - new_labels
    extra = new_labels - c.labels
    if missing:
        problems.append(f"{name}: missing edge_label(s) {sorted(missing)} — every original label must appear")
    if extra:
        problems.append(f"{name}: invented edge_label(s) {sorted(extra)} — only the original labels are allowed")

    # Structural seams must keep their drafted length — _compute_connections pairs
    # these edges with another piece, and a shorter/longer seam no longer sews.
    new_lengths = _outline_label_lengths(vertices, edge_labels)
    for label in sorted(STRUCTURAL_LABELS & c.labels & set(new_lengths)):
        old_len = c.label_lengths.get(label, 0.0)
        if old_len <= 1e-6:
            continue
        new_len = new_lengths[label]
        if abs(new_len - old_len) / old_len > SEAM_LENGTH_TOLERANCE:
            problems.append(
                f"{name}: the '{label}' seam is {new_len:.1f} cm but was drafted {old_len:.1f} cm — "
                f"structural seams must stay within {SEAM_LENGTH_TOLERANCE:.0%} or the pieces "
                f"no longer sew together; reshape the free edges instead"
            )

    xs = [v.x for v in vertices]
    ys = [v.y for v in vertices]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    for dim, new, old in (("width", width, c.width), ("height", height, c.height)):
        if old > 1e-6 and abs(new - old) / old > REFINE_MAX_DELTA:
            problems.append(
                f"{name}: {dim} {new:.1f} cm is more than {REFINE_MAX_DELTA:.0%} away from "
                f"the drafted {old:.1f} cm — stay near the drafted size"
            )

    margin = (MAX_CP_BBOX_FACTOR - 1.0) * max(width, height, 1e-6)
    for v in vertices:
        if isinstance(v, CurveSegment):
            for cp in (v.cp1, v.cp2):
                if not (min(xs) - margin <= cp.x <= max(xs) + margin
                        and min(ys) - margin <= cp.y <= max(ys) + margin):
                    problems.append(f"{name}: a bezier control point lies far outside the outline — runaway curve")
                    break

    if c.on_fold:
        if isinstance(vertices[0], CurveSegment):
            problems.append(f"{name}: the closing fold edge must be straight — the FIRST point cannot carry control points")
        diag = max((c.width ** 2 + c.height ** 2) ** 0.5, 1e-6)
        for label, v, anchor in (("first", vertices[0], c.first_vertex), ("last", vertices[-1], c.last_vertex)):
            dist = ((v.x - anchor[0]) ** 2 + (v.y - anchor[1]) ** 2) ** 0.5
            if dist > FOLD_ANCHOR_TOLERANCE * diag:
                problems.append(
                    f"{name}: the {label} point moved {dist:.1f} cm — it anchors the fold edge and must stay put"
                )

    if problems:
        return None, problems

    reason = str(entry.get("reason", "") or "").strip()
    cx = (min(xs) + max(xs)) / 2
    spec = PieceSpec(
        name=name,
        outline=vertices,
        darts=[],
        grain_start=Point(cx, min(ys) + height * 0.15),
        grain_end=Point(cx, min(ys) + height * 0.85),
        cut_qty=c.cut_qty,
        on_fold=c.on_fold,
        seam_allowance=c.seam_allowance,
        notes=(
            "reshaped from the photo (AI refine); verify the shape before cutting"
            + (f" — {reason}" if reason else "")
        ),
        edge_labels=edge_labels,
        source="vision",
        detail="photo_refine",
    )
    geometry_problems = validate_spec(spec, measurements)
    if geometry_problems:
        return None, [f"{name}: {p}" for p in geometry_problems]
    return spec, []


# ── Apply ──────────────────────────────────────────────────────────────────────

def _apply_refinements(psnap: dict, accepted: dict[str, PieceSpec], ctx: dict[str, _PieceCtx]) -> dict:
    """Splice accepted outlines into a copy of the psnap.

    The piece keeps its id and canvas position; only its outline elements are
    replaced. Interior elements (darts, marks, the original grain line) are left
    untouched, and connections are recomputed at the end."""
    result = json.loads(json.dumps(psnap))
    if not accepted:
        return result

    replaced_ids = {eid for name in accepted for eid in ctx[name].outline_ids}
    elements = [e for e in result["elements"] if e["id"] not in replaced_ids]

    pieces_by_name = {p.get("name"): p for p in result.get("pieces", [])}
    for name, spec in accepted.items():
        c = ctx[name]
        new_elems, piece_dict = _serialise_piece(
            spec, offset_x=c.offset_x, offset_y=c.offset_y, piece_id=c.piece_id,
        )
        # Keep the piece's original grain-line element; drop the freshly minted one.
        new_elems = [e for e in new_elems if e["type"] != "grain-line"]
        elements.extend(new_elems)

        piece = pieces_by_name[name]
        piece["elementIds"] = piece_dict["elementIds"]
        piece["source"] = "vision"
        piece["detail"] = "photo_refine"
        piece["notes"] = spec.notes

    result["elements"] = elements
    result["connections"] = _compute_connections(elements, result.get("pieces", []))
    return result


# ── Public API ─────────────────────────────────────────────────────────────────

def _user_prompt(
    garment_type: GarmentType,
    measurements: Measurements,
    compact: list[dict],
    notes: str,
    problems: list[str] | None = None,
) -> str:
    text = (
        f"Garment type: {garment_type.value}\n"
        f"Body measurements (cm): chest={measurements.chest_cm}, waist={measurements.waist_cm}, "
        f"hip={measurements.hip_cm}, length={measurements.length_cm}\n"
    )
    if notes:
        text += f"Analysis notes about this garment: {notes}\n"
    text += (
        "\nDrafted pattern pieces:\n"
        + json.dumps({"pieces": compact}, ensure_ascii=False)
        + "\n\nCompare each piece against the photo and return the JSON object."
    )
    if problems:
        text += (
            "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED for these reasons:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nFix every problem and return the corrected JSON object."
        )
    return text


async def refine_pattern(
    psnap: dict,
    garment_type: GarmentType,
    measurements: Measurements,
    front_bytes: bytes,
    back_bytes: bytes | None = None,
    notes: str = "",
) -> tuple[dict, dict]:
    """Run the photo-refine pass. Returns (updated_psnap, summary).

    Raises ValueError for unusable input (no pieces) and lets provider errors
    (LLMError subclasses) propagate for the API layer to map. Any piece the
    model returns that fails validation is dropped — the worst case is an
    unchanged psnap, never a corrupted one."""
    begin_refine()
    compact, ctx = _pieces_to_compact(psnap)
    if not compact:
        raise ValueError("the pattern has no pieces to refine")

    trace_request = {
        "garment_type": garment_type.value,
        "piece_count": len(compact),
        "front_image_bytes": len(front_bytes),
        "back_image_bytes": len(back_bytes) if back_bytes else None,
    }
    images = [front_bytes] if back_bytes is None else [front_bytes, back_bytes]
    user_prompts: list[str] = []
    raw_responses: list[str] = []
    accepted: dict[str, PieceSpec] = {}
    rejected: dict[str, str] = {}
    salvage_pool: dict[str, PieceSpec] = {}
    problems: list[str] = []

    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            user = _user_prompt(garment_type, measurements, compact, notes, problems or None)
            user_prompts.append(user)
            response = await acomplete_with_retry(
                get_provider(),
                system=_REFINE_SYSTEM_PROMPT,
                user_text=user,
                max_tokens=_MAX_RESPONSE_TOKENS,
                images=images,
                temperature=0,
            )
            raw_responses.append(response.text)
            add_event(
                "refine_attempt", attempt=attempt,
                problems_sent=list(problems), truncated=response.truncated,
            )

            try:
                data = parse_json_response(response.text)
                entries = data.get("pieces")
                if not isinstance(entries, list):
                    raise ValueError("the response must be {\"pieces\": [...]}")
            except ValueError as exc:
                if response.truncated:
                    # Cut off at the token limit — recover the complete piece
                    # objects instead of rejecting the whole response.
                    entries = _salvage_pieces(response.text)
                    add_event("refine_truncated_salvage", pieces_recovered=len(entries))
                    if not entries:
                        problems = [
                            "your response was cut off at the token limit — return only the "
                            "pieces that truly disagree with the photo, with fewer outline points"
                        ]
                        accepted, rejected = {}, {"(response)": "truncated at the token limit"}
                        continue
                else:
                    problems = [str(exc)]
                    accepted, rejected = {}, {"(response)": str(exc)}
                    continue

            accepted, rejected = {}, {}
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    rejected[f"(entry {idx})"] = "each piece must be a JSON object"
                    continue
                spec, entry_problems = _validate_entry(entry, ctx, measurements)
                if spec is not None:
                    accepted[spec.name] = spec
                else:
                    rejected[str(entry.get("name") or f"(entry {idx})")] = "; ".join(entry_problems)

            if accepted:
                # Best-so-far: if a repair attempt regresses to nothing, the pieces
                # already validated on this attempt are still applied.
                salvage_pool = dict(accepted)
            if not rejected and not response.truncated:
                break
            problems = [reason for reason in rejected.values()]
            if response.truncated:
                problems.append(
                    "your response was cut off at the token limit — return only the pieces "
                    "that truly disagree with the photo, with fewer outline points"
                )
        # Final attempt: keep the valid pieces, drop the invalid ones (partial acceptance).
        if not accepted and salvage_pool:
            accepted = salvage_pool
            rejected = {n: r for n, r in rejected.items() if n not in accepted}
            add_event("refine_kept_previous_attempt", pieces=sorted(accepted))

        for name in accepted:
            add_event("refine_piece_accepted", name=name)
        for name, reason in rejected.items():
            add_event("refine_piece_rejected", name=name, reason=reason)
            logger.info("Refine rejected piece %s: %s", name, reason)

        updated = _apply_refinements(psnap, accepted, ctx)
        summary = {
            "changed": sorted(accepted),
            "rejected": [{"name": n, "reason": r} for n, r in sorted(rejected.items())],
            "unchanged": sorted(set(ctx) - set(accepted)),
        }
    except Exception as exc:
        trace_refine(trace_request, _REFINE_SYSTEM_PROMPT, user_prompts, raw_responses, None, error=str(exc))
        raise

    trace_refine(trace_request, _REFINE_SYSTEM_PROMPT, user_prompts, raw_responses, summary)
    return updated, summary
