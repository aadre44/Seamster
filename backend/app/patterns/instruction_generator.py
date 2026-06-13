import logging

from pydantic import BaseModel

from app.llm import acomplete_with_retry, get_provider, parse_json_response
from app.models.features import GarmentFeatures
from app.models.measurements import Measurements


class PieceInfo(BaseModel):
    name: str
    cut_qty: int = 2
    on_fold: bool = False
    seam_allowance: float = 1.5
    notes: str = ""

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are an expert sewing instructor. Generate concise, accurate step-by-step sewing instructions
for home sewists working from printed pattern pieces.

Rules:
- Each step is 1-2 sentences: one clear action and the immediate result. No technique explanations.
- Reference piece names EXACTLY as given (e.g. "Front Panel", "Cuff Band").
- Follow correct construction order: prepare fabric → cut & mark → interface → construct body
  → attach closures → collar/sleeves → finish → press.
- Use metric measurements (cm) throughout.
- Tips are optional and only for genuinely easy-to-miss mistakes (1 sentence max).

Output format — return ONLY valid JSON, no markdown fences, no extra text:
{
  "garment_summary": "<one sentence describing the garment>",
  "sections": [
    {
      "title": "<section title>",
      "steps": [
        {
          "number": <integer>,
          "instruction": "<action and result, 1-2 sentences>",
          "tip": "<optional: one sentence warning about a common mistake>"
        }
      ]
    }
  ]
}

Include only sections relevant to this garment. Step numbers are consecutive across all sections (1, 2, 3 … N).
"""


_GARMENT_TOKEN_WEIGHTS: dict[str, float] = {
    "coat":     2.2,
    "jacket":   2.0,
    "blazer":   1.8,
    "dress":    1.6,
    "shirt":    1.5,
    "blouse":   1.5,
    "trousers": 1.4,
    "pants":    1.4,
    "shorts":   1.2,
    "bodice":   1.3,
    "skirt":    1.0,
}


def _compute_max_tokens(features: GarmentFeatures, pieces: list[PieceInfo]) -> int:
    base = 2048
    per_piece = len(pieces) * 250
    per_detail = len(features.details) * 80 if features.details else 0
    sleeve_extra = 200 if features.sleeve_length and features.sleeve_length != "sleeveless" else 0
    neckline_extra = 100 if features.neckline else 0

    garment_key = features.garment_type.value.lower()
    multiplier = _GARMENT_TOKEN_WEIGHTS.get(garment_key, 1.0)

    raw = int((base + per_piece + per_detail + sleeve_extra + neckline_extra) * multiplier)
    return max(4096, min(8192, raw))


def _build_user_prompt(
    features: GarmentFeatures,
    measurements: Measurements,
    pieces: list[PieceInfo],
) -> str:
    lines: list[str] = [
        f"Garment type: {features.garment_type.value}",
        f"Silhouette: {features.silhouette}",
        f"Length category: {features.length_category}",
    ]

    if features.sleeve_length:
        lines.append(f"Sleeve length: {features.sleeve_length}")
    if features.neckline:
        lines.append(f"Neckline: {features.neckline}")

    closure = features.closure
    lines.append(f"Closure: {closure.type} at {closure.position}")

    if features.waistband:
        wb = features.waistband
        lines.append(f"Waistband: {wb.type} type, approx {wb.width_cm_estimate} cm wide")
    else:
        lines.append("Waistband: none")

    if features.darts:
        d = features.darts
        lines.append(f"Darts: {d.front} front, {d.back} back")

    if features.details:
        lines.append(f"Construction details: {', '.join(features.details)}")

    lines.append(
        f"Measurements: waist {measurements.waist_cm} cm, hip {measurements.hip_cm} cm, "
        f"waist-to-hip {measurements.waist_to_hip_cm} cm, garment length {measurements.length_cm} cm"
    )
    if measurements.chest_cm:
        lines.append(f"  chest {measurements.chest_cm} cm")
    if measurements.shoulder_width_cm:
        lines.append(f"  shoulder width {measurements.shoulder_width_cm} cm")
    if measurements.arm_length_cm:
        lines.append(f"  arm length {measurements.arm_length_cm} cm")
    if measurements.inseam_cm:
        lines.append(f"  inseam {measurements.inseam_cm} cm")

    lines.append(f"Seam allowance: {measurements.seam_allowance_cm} cm")
    lines.append(f"Hem allowance: {measurements.hem_allowance_cm} cm")

    if features.notes:
        lines.append(f"Pattern notes: {features.notes}")

    lines.append("")
    lines.append("Generated pattern pieces:")
    for p in pieces:
        attrs: list[str] = [f"cut x{p.cut_qty}"]
        if p.on_fold:
            attrs.append("cut on fold")
        if p.seam_allowance != measurements.seam_allowance_cm:
            attrs.append(f"seam allowance {p.seam_allowance} cm")
        piece_line = f"  • {p.name} ({', '.join(attrs)})"
        if p.notes:
            piece_line += f" — {p.notes}"
        lines.append(piece_line)

    lines.append("")
    lines.append(
        "Write complete step-by-step sewing instructions for this garment from pre-washing to final press. "
        "Base the cutting, interfacing, and construction steps on the exact pieces listed above. "
        "Keep each step to 1-2 sentences. Return only the JSON object described in the system prompt."
    )

    return "\n".join(lines)


async def generate_instructions(
    features: GarmentFeatures,
    measurements: Measurements,
    pieces: list[PieceInfo],
) -> dict:
    """Call the configured LLM and return structured sewing instructions as a dict."""
    user_prompt = _build_user_prompt(features, measurements, pieces)
    max_tokens = _compute_max_tokens(features, pieces)
    logger.debug("Computed max_tokens=%d for %s with %d pieces", max_tokens, features.garment_type.value, len(pieces))

    response = await acomplete_with_retry(
        get_provider(),
        system=_SYSTEM_PROMPT,
        user_text=user_prompt,
        max_tokens=max_tokens,
    )

    logger.debug("Instructions raw response length: %d chars", len(response.text))
    if response.truncated:
        raise ValueError(
            "The LLM's response was cut off because the garment description produced too many "
            "instructions. Try reducing the number of pattern pieces or garment details."
        )
    return parse_json_response(response.text)
