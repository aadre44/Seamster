"""LLM fallback for generating pattern pieces not handled by the parametric engine.

When the engine detects a garment detail it cannot produce geometrically
(e.g. spaghetti_straps, drawstring_hood, belt), this module:

  1. Checks the learned TemplateStore — if a template exists, uses it directly.
  2. If no template exists, calls Claude with a structured prompt that asks for
     piece dimensions as *parametric formulas* (not absolute coordinates).
  3. Parses the LLM response, saves it as a PieceTemplate, and applies it.

Saving as a formula-based template means the piece can be re-used for any
body size without another LLM call, and the parametric engine grows over time.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

import anthropic

from app.models.features import GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.learned_pieces import PieceTemplate, apply_template, get_store
from app.patterns.skirts import PieceSpec

logger = logging.getLogger(__name__)

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
})

_PARAMETRIC_DETAILS: dict[str, set[str]] = {
    "shirt":    {"button_placket", "collar", "cuffs", "chest_pocket", "patch_pockets"}
                | _TECHNIQUES,
    "blouse":   {"collar"} | _TECHNIQUES,
    "skirt":    {"patch_pockets", "patch_pocket_flap", "side_pockets", "welt_pockets",
                 "kick_pleat", "side_slits", "ruffle", "elastic_waist"} | _TECHNIQUES,
    "trousers": {"patch_pockets", "side_pockets", "welt_pockets", "cargo_pocket",
                 "fly_shield", "cuffs", "elastic_waist",
                 "high_rise", "low_rise", "ultra_high_rise", "pleats"} | _TECHNIQUES,
    "pants":    {"patch_pockets", "side_pockets", "welt_pockets", "cargo_pocket",
                 "cuffs", "elastic_waist", "drawstring",
                 "high_rise", "low_rise"} | _TECHNIQUES,
    "shorts":   {"patch_pockets", "side_pockets", "cuffs", "elastic_waist"} | _TECHNIQUES,
    "jacket":   {
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
                    # outerwear extras (now parametrically handled)
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
                } | _TECHNIQUES,
    "blazer":   {
                    "collar",
                    "notch_lapel", "peak_lapel", "shawl_collar", "band_collar",
                    "lapels", "facing", "back_yoke",
                    "single_breasted", "double_breasted",
                    "patch_pockets", "welt_pockets", "lining_visible",
                    "breast_pocket", "chest_pocket", "chest_welt", "in_seam_pockets",
                    "two_piece_sleeve", "tailored_sleeve",
                    "cuffs", "button_cuff", "sleeve_placket", "cuff_vent",
                } | _TECHNIQUES,
    "bodice":   set() | _TECHNIQUES,
    "coat":     set() | _TECHNIQUES,
    "dress":    set() | _TECHNIQUES,
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
      "geometry": "rectangle",
      "length_formula": "<arithmetic expression using measurement variables>",
      "width_formula": "<arithmetic expression or numeric literal>",
      "cut_qty": <integer — how many pieces to cut from fabric>,
      "on_fold": <true | false>,
      "seam_allowance_formula": "seam_allowance_cm",
      "grain_direction": "<'length' runs the grain along the longer dimension | 'width'>",
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

Geometry rules:
- "rectangle" is the only supported geometry for now.
- length_formula: the longer dimension (the piece's height when upright).
- width_formula: the shorter dimension (the piece's width when upright).
- grain_direction "length": grain arrow runs parallel to the length axis (vertical).
- grain_direction "width": grain arrow runs parallel to the width axis (horizontal).

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
) -> str:
    return (
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
        f"  seam_allowance_cm={measurements.seam_allowance_cm}\n\n"
        f"Return only the JSON object."
    )


# ── Public API ────────────────────────────────────────────────────────────────

def detect_unsupported_details(features: GarmentFeatures) -> list[str]:
    """Return detail strings that the parametric engine cannot produce geometrically."""
    handled = _PARAMETRIC_DETAILS.get(features.garment_type.value, set())
    return [d for d in features.details if d not in handled]


def generate_novel_pieces(
    unsupported_details: list[str],
    features: GarmentFeatures,
    measurements: Measurements,
) -> list[PieceSpec]:
    """Produce PieceSpecs for each unsupported detail.

    Template-first: hits the learned store before calling the LLM.
    Newly generated templates are saved immediately so future requests are free.
    Returns an empty list (not an error) if the API key is missing or a call fails.
    """
    if not unsupported_details:
        return []

    store = get_store()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — skipping LLM fallback for: %s",
            unsupported_details,
        )
        return []

    client = anthropic.Anthropic(api_key=api_key)
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

        # ── 2. Call the LLM ───────────────────────────────────────────────────
        logger.info("LLM fallback: generating piece for detail='%s' on '%s'", detail, gtype)
        try:
            response = client.messages.create(
                model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": _user_prompt(detail, features, measurements)},
                ],
            )
            raw_text = response.content[0].text
        except Exception:
            logger.exception("Anthropic API call failed for detail='%s'", detail)
            continue

        # ── 3. Parse response ─────────────────────────────────────────────────
        try:
            pieces_data = _parse_response(raw_text)
        except Exception:
            logger.exception(
                "Failed to parse LLM response for detail='%s': %r", detail, raw_text
            )
            continue

        # ── 4. Save each returned piece as a template, then apply it ─────────
        for idx, pd in enumerate(pieces_data):
            suffix = "" if idx == 0 else f"_part{idx}"
            tid = f"{detail}{suffix}-{gtype}-v1"

            new_template = PieceTemplate(
                id=tid,
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
                created_at=datetime.now(timezone.utc).isoformat(),
                times_used=1,
            )

            store.add(new_template)
            logger.info("Saved new template id='%s' (detail=%s, garment=%s)", tid, detail, gtype)

            try:
                result_specs.append(apply_template(new_template, measurements))
            except Exception:
                logger.exception("Failed to apply new template '%s'", tid)

    return result_specs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    # Strip markdown code fences if the model added them despite instructions
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text).get("pieces", [])


def _humanise(detail: str) -> str:
    return detail.replace("_", " ").title()
