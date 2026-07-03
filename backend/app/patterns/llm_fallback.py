"""LLM fallback for generating pattern pieces not handled by the parametric engine.

When the engine detects a garment detail it cannot produce geometrically
(e.g. spaghetti_straps, drawstring_hood, belt), this module:

  1. Checks the learned TemplateStore — if a template exists, uses it directly.
  2. If no template exists, calls Claude with a structured prompt that asks for
     piece dimensions as *parametric formulas* (not absolute coordinates).
  3. Validates every returned piece (dimension bounds, self-intersection,
     flounce attachment-edge length vs the real garment edge) and re-prompts
     with the validation errors up to two repair rounds before falling back to
     a clearly-marked placeholder rectangle.
  4. Saves accepted pieces as PieceTemplates and applies them.

Saving as a formula-based template means the piece can be re-used for any
body size without another LLM call, and the parametric engine grows over time.
Pieces that declare an attachment_label carry that seamLabel on their
attachment edge, so the engine's connection pass sews them into the assembly.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from app.llm import LLMError, complete_with_retry, get_provider
from app.models.features import GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.learned_pieces import (
    PieceTemplate,
    _eval_formula,
    _measurement_namespace,
    apply_template,
    get_store,
)
from app.patterns.novel_validation import ARC_TOLERANCE, ATTACHMENT_LABELS, validate_spec
from app.patterns.skirts import PieceSpec

logger = logging.getLogger(__name__)

# 1 initial LLM call + 2 repair re-prompts per detail, then the placeholder fallback.
_MAX_ATTEMPTS = 3

# ── What the parametric engine already handles natively ───────────────────────
# Details listed here are produced by the parametric builders and must NOT be
# forwarded to the LLM fallback — doing so generates duplicate pieces.
# Any detail NOT listed here (including unknown/novel pocket names) falls through
# to the LLM, which generates a piece from the detail name + garment context.

# Technique-only detail strings that never produce a separate pattern piece.
# Blocked for ALL garment types via the _TECHNIQUES set below.
_TECHNIQUES: frozenset[str] = frozenset({
    "topstitching", "contrast_stitching", "topstitching_detail",
    "bar_tacks", "edge_stitching", "blind_stitch", "flat_felled_seam",
    "quilting", "embroidery",
    # visual description — no standalone piece regardless of garment type
    "lining_visible",
    # closure/styling tokens — shape the garment but produce no standalone piece
    "single_breasted", "double_breasted",
    "moto_zip", "asymmetric_zip", "center_zip", "snap_front",
    "action_back",
    # pocket-shape modifiers — change an existing patch pocket's bottom edge, not a piece
    "pocket_pointed", "pocket_rounded", "pocket_angled", "pocket_curved",
    # pleat modifiers — handled by the engine (allowance + fold markings on the panel)
    "pleats", "pleated",
    # gathering/shirring technique — no standalone piece
    "smocking",
    # neckline descriptors that sometimes leak into details — the neckline field
    # already drives the geometry, so these never produce a standalone piece
    "v_neck", "round_neck", "v_neckline", "scoop_neck",
})

# Several garment types share one generator, so they MUST share one detail set —
# otherwise the registry drifts and the fallback duplicates pieces the shared
# builder already produced. These shared sets are defined once and reused below.
# (test_parametric_registry_sync.py guards this invariant.)

# shirt + blouse → _generate_shirt_pattern
# Strap / tie tokens are now owned by the structured `construction` field (the strap is
# integral to the halter front, or a styling detail) — register them so the fallback does
# NOT emit duplicate strap rectangles. `elastic_hem`/`drawstring_hem` build a native Hem
# Casing Band, so they must be registered too.
_SHIRT_DETAILS: set[str] = {
    "button_placket", "collar", "ribbed_collar", "cuffs", "chest_pocket", "patch_pockets",
    "spaghetti_straps", "straps", "halter_strap", "wide_straps", "one_shoulder",
    "racerback", "tie_front",
    "elastic_hem", "drawstring_hem", "ruffles", "ruffle",
}

# trousers + pants → _generate_trousers_pattern
# Cargo synonyms (cargo/bellows/flap/utility, singular + plural) all map to the one native
# Cargo Pocket + Flap pair (_CARGO_POCKET_TOKENS in engine.py), so the fallback never adds
# a duplicate bag + flap for the same physical pocket.
_TROUSER_DETAILS: set[str] = {
    "patch_pockets", "side_pockets", "welt_pockets",
    "cargo_pocket", "cargo_pockets", "cargo",
    "bellows_pocket", "bellows_pockets",
    "flap_pocket", "flap_pockets", "pocket_flap", "patch_pocket_flap",
    "utility_pocket", "utility_pockets",
    "cargo_flat", "flat_cargo", "cargo_gusset", "gusset_cargo",
    "fly_shield", "cuffs", "elastic_waist", "belt_loops", "drawstring",
    "high_rise", "low_rise", "ultra_high_rise",
}

# jacket + blazer → _generate_jacket_pattern
# vest → _generate_vest_pattern. Bindings, facings and welt pockets are driven by the
# structured fields (binding / facings / welt_pockets) but the analysis may also emit the
# equivalent loose detail tokens; register them so the fallback never duplicates the piece.
_VEST_DETAILS: set[str] = {
    "neckline_binding", "contrast_binding", "binding", "piping",
    "armhole_binding", "hem_binding",
    "armhole_facing", "hem_facing", "neckline_facing", "facing",
    "welt_pockets", "besom_pockets",
    # neckline descriptors that may leak into details — the neckline field drives geometry
    "notched_v", "split_v", "notched_neckline",
    # mandarin/band stand collar — built natively by the vest block
    "mandarin_collar", "band_collar", "stand_collar", "mandarin", "collar",
    # asymmetric wrap front — built natively (overlap + underlap panels)
    "asymmetric_wrap", "asymmetric_front", "wrap_front", "diagonal_closure",
}

_JACKET_DETAILS: set[str] = {
    # structural / facing
    "collar",
    "notch_lapel", "peak_lapel", "shawl_collar", "band_collar", "no_collar",
    "lapels", "facing", "back_yoke", "yoke", "western_yoke",
    "lining_visible",
    # breast style
    "single_breasted", "double_breasted",
    # pockets
    "patch_pockets", "welt_pockets",
    "side_pockets", "in_seam_pockets", "slash_pockets",
    "breast_pocket", "chest_pocket", "chest_welt",
    # outerwear extras
    "hood",
    "epaulets", "epaulet_tab", "shoulder_tab",
    "belt", "belt_strap", "self_belt",
    "belt_loops", "drawstring_hem",
    # rib / knit trim
    "cuff_band", "hem_band",
    "ribbed_cuffs", "ribbed_hem", "knit_cuffs", "knit_hem",
    # cuff / sleeve finishing
    "cuffs", "button_cuff", "snap_cuff", "woven_cuff",
    "sleeve_placket", "cuff_vent",
    "two_piece_sleeve", "tailored_sleeve",
}

_PARAMETRIC_DETAILS: dict[str, set[str]] = {
    "shirt":    _SHIRT_DETAILS | _TECHNIQUES,
    "blouse":   _SHIRT_DETAILS | _TECHNIQUES,
    "skirt":    {"patch_pockets", "patch_pocket_flap", "side_pockets", "welt_pockets",
                 "kick_pleat", "side_slits", "ruffle", "elastic_waist"} | _TECHNIQUES,
    "trousers": _TROUSER_DETAILS | _TECHNIQUES,
    "pants":    _TROUSER_DETAILS | _TECHNIQUES,
    "jacket":   _JACKET_DETAILS | _TECHNIQUES,
    "blazer":   _JACKET_DETAILS | _TECHNIQUES,
    "vest":     _VEST_DETAILS | _TECHNIQUES,
    "bodice":   set() | _TECHNIQUES,
    # Dress generator natively builds a collar, belt/sash, and side pocket bag.
    "dress":    {"collar", "belt", "sash", "tie_back",
                 "side_pockets", "patch_pockets"} | _TECHNIQUES,
    # Composed garments (patterns/compositions.py) inherit the detail sets of the
    # builders they are composed from, or the fallback duplicates component pieces.
    "shorts":   _TROUSER_DETAILS | _TECHNIQUES,
    "coat":     _JACKET_DETAILS | _TECHNIQUES,
    "tunic":    _SHIRT_DETAILS | _TECHNIQUES,
    "romper":   _SHIRT_DETAILS | _TROUSER_DETAILS | _TECHNIQUES,
    "jumpsuit": _SHIRT_DETAILS | _TROUSER_DETAILS | _TECHNIQUES,
}

# ── LLM prompt ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert sewing pattern maker. A parametric pattern engine has generated \
the main pieces for a garment but cannot handle a specific feature. Your job is to \
describe the missing pattern piece(s) as parametric formulas so they can be saved \
as reusable templates.

Respond with ONLY a valid JSON object — no markdown fences, no commentary.

Required format:
{
  "pieces": [
    {
      "name": "<piece name shown on the pattern, e.g. Strap>",
      "description": "<one sentence for the pattern maker>",
      "geometry": "<rectangle | shaped_rectangle | trapezoid | godet | quarter_circle | half_circle | curved_band | custom>",
      "length_formula": "<arithmetic expression using measurement variables>",
      "width_formula": "<arithmetic expression or numeric literal>",
      "cut_qty": <integer — how many pieces to cut from fabric>,
      "on_fold": <true | false>,
      "seam_allowance_formula": "seam_allowance_cm",
      "grain_direction": "<'length' runs the grain along the longer dimension | 'width'>",
      "top_width_formula": "<trapezoid only: top edge width — omit otherwise>",
      "curve_depth_formula": "<curved_band only: arc rise — omit otherwise>",
      "end_shape": "<shaped_rectangle only: square | rounded | angled | pointed | curved — omit otherwise>",
      "attachment_label": "<the garment edge this piece is SEWN TO: hem | waist | neckline | armhole | wrist | side_seam — or null for applied/free-standing pieces (patch pockets, belts, epaulets)>",
      "points": "<custom only: array of point objects — omit otherwise>",
      "attachment_edges": "<custom only: array of 0-based edge indices that sew to attachment_label — omit otherwise>",
      "reasoning": "<brief explanation of why these dimensions make sense>"
    }
  ]
}

Available measurement variables (all in cm, use 0-safe fallback constants if needed):
  waist_cm, hip_cm, waist_to_hip_cm, length_cm
  chest_cm (default 90 if not measured)
  shoulder_width_cm (default 38 if not measured)
  arm_length_cm (default 60 if not measured)
  seam_allowance_cm (typically 1.5)

Allowed in formulas: the variables above, numeric literals, +, -, *, /, (, ), max(), min().
No other functions or identifiers are permitted.

Geometry options — pick the one that matches the REAL pattern-piece shape:
- "rectangle": straps, ties, simple bands, casings, plain patch pockets.
  length_formula = longer dimension, width_formula = shorter dimension.
  grain_direction "length" = grain along the length axis; "width" = along the width axis.
- "shaped_rectangle": a rectangle whose bottom end is shaped — set "end_shape" to
  pointed | rounded | angled | curved. Use for flaps, tabs, shaped belt/tie ends.
  length_formula = height (shaped end at the bottom), width_formula = width.
- "trapezoid": a band/gore/panel wider at one end. width_formula = bottom edge,
  "top_width_formula" = top edge, length_formula = height.
- "godet": triangular flare insert with a curved hem. length_formula = the slit/side
  length it is sewn into, width_formula = hem width (must be < 1.8 x length).
- "quarter_circle": annular flounce/ruffle/circle-cut piece spanning 90 degrees.
  length_formula = the attachment (inner) edge length — EXACTLY the edge run it is
  sewn to, NOT gathered; width_formula = the flounce depth.
- "half_circle": as quarter_circle but spanning 180 degrees (fuller flounce, cascade,
  cape-like pieces).
- "curved_band": contoured band (shaped collar, contoured waistband, curved yoke band).
  length_formula = band run, width_formula = band height,
  "curve_depth_formula" = arc rise (omit for a gentle default of length * 0.12).
- "custom": ONLY when no primitive above fits. Provide "points": an ordered array of
  3-24 outline vertices, each {"x": "<formula>", "y": "<formula>"} — y grows downward,
  keep coordinates near the origin. To reach a vertex along a cubic bezier from the
  previous vertex, add "cp1x"/"cp1y"/"cp2x"/"cp2y" formulas to that vertex. The outline
  closes automatically from the last point back to the first. Still give length_formula/
  width_formula as the approximate overall dimensions. With attachment_label, also give
  "attachment_edges": the 0-based edge indices that sew to that garment edge (edge i runs
  from point i to point i+1).
Shape selection guidance:
- A GATHERED ruffle is a rectangle with length 1.5–2.5x the edge it attaches to;
  a CIRCULAR flounce (ungathered, fluid drape) is quarter_circle/half_circle with
  length = the attachment edge exactly.
- Only use plain "rectangle" when the real piece genuinely is one.

Key sewing conventions to follow:
- Straps: cut_qty=4 (cut 2 pairs so they can be sewn together); narrow width ~1.5–2 cm finished.
- Waistbands / belts: typically cut on fold (on_fold=true) with width formula = waistband_width_cm * 2.
- Facings: follow the edge they face; seam_allowance is usually included in width.
- When in doubt, err slightly large — the user can trim in the editor.

Pocket-type details (any detail whose name contains "pocket"):
- Simple patch/applied pocket: 1 piece only (the outer rectangle; the top seam allowance
  acts as a facing when folded under). cut_qty matches how many pockets appear.
- Pocket with button-down or velcro flap (cargo, bellows, etc.): 2 pieces — bag + flap.
  Bag: width ≈ hip_cm / 4 * 0.56, height ≈ 22 cm. Flap: same width, height ≈ 6.5 cm.
- In-seam / slash pocket: 1 piece (the bag); cut_qty=4 (front + back of each side).
- Welt pocket: 2 pieces — welt strip (narrow, ~3 cm tall) + pocket bag.
- Chest pocket on shirt/blouse: width ≈ chest_cm * 0.13, height ≈ chest_cm * 0.155, cut_qty=1.
- Back trouser patch pocket: width ≈ 14 cm, height ≈ 15 cm, cut_qty=2.
- If the pocket name is entirely unfamiliar, generate a single rectangle sized for the
  most likely placement given the garment type and notes. Never return zero pieces.
"""


def _user_prompt(
    detail: str,
    features: GarmentFeatures,
    measurements: Measurements,
    edge_runs: dict[str, float] | None = None,
    problems: list[str] | None = None,
) -> str:
    text = (
        f"Generate the missing pattern piece(s) for the feature '{detail}' "
        f"on this garment:\n\n"
        f"  garment_type: {features.garment_type.value}\n"
        f"  silhouette: {features.silhouette}\n"
        f"  sleeve_length: {features.sleeve_length}\n"
        f"  neckline: {features.neckline}\n"
        f"  notes: {features.notes}\n\n"
        f"Measurements:\n"
        f"  waist_cm={measurements.waist_cm}\n"
        f"  hip_cm={measurements.hip_cm}\n"
        f"  chest_cm={measurements.chest_cm or 'not measured (use 90.0)'}\n"
        f"  shoulder_width_cm={measurements.shoulder_width_cm or 'not measured (use 38.0)'}\n"
        f"  arm_length_cm={measurements.arm_length_cm or 'not measured (use 60.0)'}\n"
        f"  length_cm={measurements.length_cm}\n"
        f"  seam_allowance_cm={measurements.seam_allowance_cm}\n"
    )
    if edge_runs:
        runs = ", ".join(f"{label}={run:.1f}" for label, run in sorted(edge_runs.items()))
        text += (
            f"\nGarment edge run-lengths as drafted (half pattern, cm): {runs}\n"
            "If the piece sews to one of these edges, set attachment_label to that edge and size "
            "the piece's attachment edge to match it (circular flounce inner edge = the run "
            "exactly; gathered rectangle = 1.5-2.5x the run).\n"
        )
    if problems:
        text += (
            "\nYOUR PREVIOUS ATTEMPT WAS REJECTED for these reasons:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nFix every problem and return the corrected JSON object.\n"
        )
    return text + "\nReturn only the JSON object."


# ── Public API ────────────────────────────────────────────────────────────────

def detect_unsupported_details(features: GarmentFeatures) -> list[str]:
    """Return detail strings that the parametric engine cannot produce geometrically."""
    handled = _PARAMETRIC_DETAILS.get(features.garment_type.value, set())
    return [d for d in features.details if d not in handled]


def generate_novel_pieces(
    unsupported_details: list[str],
    features: GarmentFeatures,
    measurements: Measurements,
    edge_runs: dict[str, float] | None = None,
) -> list[PieceSpec]:
    """Produce PieceSpecs for each unsupported detail.

    Template-first: hits the learned store before calling the LLM. LLM output is
    validated (dimensions, self-intersection, attachment-edge length) and repaired
    via re-prompt up to _MAX_ATTEMPTS; only accepted pieces are persisted. When the
    provider answers but never produces a valid piece, a clearly-marked placeholder
    rectangle is emitted instead (never zero pieces for a responsive provider).
    Returns an empty list (not an error) if the provider is unconfigured or a call fails.

    ``edge_runs`` maps attachment labels (hem/waist/neckline/…) to the drafted
    edge run-length in cm, giving the LLM real numbers to size attachment edges to.
    """
    if not unsupported_details:
        return []

    store = get_store()
    provider = get_provider()
    gtype = features.garment_type.value
    result_specs: list[PieceSpec] = []

    for detail in unsupported_details:
        # ── 1. Try the learned store first ───────────────────────────────────
        template = store.find(detail, gtype)
        if template:
            logger.info("Learned template hit: id=%s for detail='%s'", template.id, detail)
            store.record_use(template.id)
            try:
                result_specs.append(apply_template(template, measurements))
            except Exception:
                logger.exception("Failed to apply learned template '%s'", template.id)
            continue

        # ── 2. Call the LLM with a validate/repair loop ───────────────────────
        logger.info("LLM fallback: generating piece for detail='%s' on '%s'", detail, gtype)
        result_specs.extend(
            _generate_with_repair(detail, features, measurements, edge_runs, store, provider)
        )

    return result_specs


def _generate_with_repair(
    detail: str,
    features: GarmentFeatures,
    measurements: Measurements,
    edge_runs: dict[str, float] | None,
    store,
    provider,
) -> list[PieceSpec]:
    """One detail's generate → validate → re-prompt loop.

    Non-final attempts are all-or-nothing: any invalid piece rejects the whole
    response and its problems are fed back into the next prompt. The final
    attempt salvages what it can (auto-scaling flounce arcs, keeping valid
    siblings) and falls back to a placeholder rectangle if nothing survives.
    """
    gtype = features.garment_type.value
    ns = _measurement_namespace(measurements)
    problems: list[str] = []

    for attempt in range(_MAX_ATTEMPTS):
        final = attempt == _MAX_ATTEMPTS - 1
        try:
            response = complete_with_retry(
                provider,
                system=_SYSTEM_PROMPT,
                user_text=_user_prompt(
                    detail, features, measurements, edge_runs=edge_runs, problems=problems
                ),
                max_tokens=1024,
            )
        except (LLMError, ValueError):
            # Provider unconfigured/unreachable — repair re-prompts cannot help,
            # and emitting placeholders here would surprise offline generation.
            logger.exception("LLM call failed for detail='%s'", detail)
            return []

        try:
            pieces_data = _parse_response(response.text)
        except Exception:
            logger.warning(
                "Attempt %d for detail='%s': response was not valid JSON", attempt + 1, detail
            )
            problems = ["the response was not a single valid JSON object in the required format"]
            continue
        if not pieces_data:
            problems = ["the 'pieces' array was empty — at least one piece is required"]
            continue

        accepted: list[tuple[PieceTemplate, PieceSpec]] = []
        errs: list[str] = []
        for idx, pd in enumerate(pieces_data):
            candidate = _template_from_dict(detail, gtype, idx, pd)

            mismatch = _arc_mismatch(candidate, ns, edge_runs)
            if mismatch is not None:
                actual, target = mismatch
                if final:
                    # Salvage: scale the arc formula onto the real edge (stays parametric).
                    _autoscale_arc(candidate, actual, target)
                else:
                    errs.append(
                        f"piece '{candidate.name}': its inner (attachment) edge measures "
                        f"{actual:.1f} cm but the garment's {candidate.attachment_label} edge "
                        f"measures {target:.1f} cm — size the attachment edge to match"
                    )
                    continue

            try:
                spec = apply_template(candidate, measurements)
            except Exception as exc:
                errs.append(f"piece '{candidate.name}' failed to build: {exc}")
                continue

            piece_problems = validate_spec(spec, measurements)
            if piece_problems:
                errs.extend(piece_problems)
                continue
            accepted.append((candidate, spec))

        if errs and not final:
            logger.info(
                "Attempt %d for detail='%s' rejected: %s", attempt + 1, detail, "; ".join(errs)
            )
            problems = errs
            continue

        if accepted:
            for tmpl, _ in accepted:
                store.add(tmpl)
                logger.info(
                    "Saved new template id='%s' (detail=%s, garment=%s)", tmpl.id, detail, gtype
                )
            return [spec for _, spec in accepted]
        break  # the final attempt produced nothing usable

    logger.warning("All attempts failed for detail='%s' — emitting placeholder", detail)
    return [_fallback_piece(detail, measurements)]


def _template_from_dict(detail: str, gtype: str, idx: int, pd: dict) -> PieceTemplate:
    """Build a PieceTemplate from one piece dict of the LLM response."""
    suffix = "" if idx == 0 else f"_part{idx}"
    attachment = pd.get("attachment_label")
    if attachment not in ATTACHMENT_LABELS:
        attachment = None
    raw_edges = pd.get("attachment_edges")
    attachment_edges = (
        [int(i) for i in raw_edges if isinstance(i, (int, float))]
        if isinstance(raw_edges, list) else None
    )
    points = pd.get("points")
    return PieceTemplate(
        id=f"{detail}{suffix}-{gtype}-v1",
        trigger_detail=detail,
        garment_types=[gtype],
        name=pd.get("name", _humanise(detail)),
        description=pd.get("description", ""),
        geometry=pd.get("geometry", "rectangle"),
        length_formula=pd.get("length_formula", "50.0"),
        width_formula=pd.get("width_formula", "1.5"),
        cut_qty=int(pd.get("cut_qty", 2)),
        on_fold=bool(pd.get("on_fold", False)),
        seam_allowance_formula=pd.get("seam_allowance_formula", "seam_allowance_cm"),
        grain_direction=pd.get("grain_direction", "length"),
        top_width_formula=pd.get("top_width_formula"),
        curve_depth_formula=pd.get("curve_depth_formula"),
        end_shape=pd.get("end_shape", "square"),
        attachment_label=attachment,
        points=points if isinstance(points, list) else None,
        attachment_edges=attachment_edges,
        created_at=datetime.now(timezone.utc).isoformat(),
        times_used=1,
    )


def _arc_mismatch(
    template: PieceTemplate, ns: dict, edge_runs: dict[str, float] | None,
) -> tuple[float, float] | None:
    """Return (actual, target) when a circular flounce's inner arc misses the
    garment edge it attaches to by more than ARC_TOLERANCE, else None."""
    if template.geometry not in ("quarter_circle", "half_circle"):
        return None
    label = template.attachment_label
    if not label or not edge_runs or label not in edge_runs:
        return None
    target = edge_runs[label]
    if target <= 0:
        return None
    try:
        actual = _eval_formula(template.length_formula, ns)
    except ValueError:
        return None  # unsafe formula — apply_template will reject it with a clearer error
    if abs(actual - target) / target > ARC_TOLERANCE:
        return actual, target
    return None


def _autoscale_arc(template: PieceTemplate, actual: float, target: float) -> None:
    """Rescale a flounce's attachment-edge formula onto the real edge length.
    Wrapping the original expression keeps the template parametric."""
    ratio = target / actual
    template.length_formula = f"({template.length_formula}) * {ratio:.4f}"
    logger.info(
        "Auto-scaled '%s' attachment edge %.1f -> %.1f cm (x%.4f)",
        template.id, actual, target, ratio,
    )


def _fallback_piece(detail: str, measurements: Measurements) -> PieceSpec:
    """Last-resort placeholder so a recognised detail never silently vanishes.
    Deliberately NOT saved to the store — it is a guess, not a learned shape."""
    template = PieceTemplate(
        id=f"{detail}-fallback",
        trigger_detail=detail,
        garment_types=[],
        name=_humanise(detail),
        description="placeholder",
        geometry="rectangle",
        length_formula="25.0",
        width_formula="12.0",
        cut_qty=1,
    )
    spec = apply_template(template, measurements)
    spec.notes = (
        f"placeholder for '{_humanise(detail)}': the AI could not produce a valid piece; "
        "this rectangle stands in — reshape it in the editor"
    )
    return spec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    # Strip markdown code fences if the model added them despite instructions
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text).get("pieces", [])


def _humanise(detail: str) -> str:
    return detail.replace("_", " ").title()
