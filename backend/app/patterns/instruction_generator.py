import asyncio
import json
import logging
import os

import anthropic

from app.models.features import GarmentFeatures
from app.models.measurements import Measurements

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_SYSTEM_PROMPT = """\
You are an expert sewing instructor and pattern maker with deep knowledge of garment construction,
couture techniques, and industrial methods. Your instructions are used by people sewing from
home-printed pattern pieces, so you must be accurate, practical, and clear.

Style rules:
- Write for a beginner who is motivated and willing to learn — explain WHY each step matters, not just WHAT to do.
- Do not simplify or omit advanced techniques when they are the correct method (e.g. understitching, clipping
  curves, stay-stitching, notching, flat-felled seams, French seams, hand-picking a zip, slip-stitching a
  lining). Explain them in plain language the first time they appear.
- Reference piece names EXACTLY as given in the context (e.g. "Front Panel", "Waistband").
- Follow correct construction order: prepare fabric → cut & mark → interface → construct body
  → attach closures → attach waistband/collar/sleeves → finish → press.
- Seam allowances included in the pattern: construct with the right side together unless stated otherwise.
- Use metric measurements (cm) throughout.

Output format — return ONLY valid JSON, no markdown fences, no extra text:
{
  "garment_summary": "<one sentence describing the garment>",
  "sections": [
    {
      "title": "<section title>",
      "steps": [
        {
          "number": <integer>,
          "instruction": "<the action to take, 1-3 sentences>",
          "technique": "<optional: name and explain the sewing technique used, 1-4 sentences>",
          "tip": "<optional: beginner-friendly note or common mistake to avoid, 1-2 sentences>"
        }
      ]
    }
  ]
}

Include only sections that are relevant to this specific garment. Omit empty sections entirely.
Step numbers must be consecutive across all sections combined (1, 2, 3 … N).
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


def _compute_max_tokens(features: GarmentFeatures, piece_names: list[str]) -> int:
    base = 2048
    per_piece = len(piece_names) * 350
    per_detail = len(features.details) * 120 if features.details else 0
    sleeve_extra = 300 if features.sleeve_length and features.sleeve_length != "sleeveless" else 0
    neckline_extra = 150 if features.neckline else 0

    garment_key = features.garment_type.value.lower()
    multiplier = _GARMENT_TOKEN_WEIGHTS.get(garment_key, 1.0)

    raw = int((base + per_piece + per_detail + sleeve_extra + neckline_extra) * multiplier)
    return max(4096, min(8192, raw))


def _build_user_prompt(
    features: GarmentFeatures,
    measurements: Measurements,
    piece_names: list[str],
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

    lines.append(f"Seam allowance included in pattern: {measurements.seam_allowance_cm} cm")
    lines.append(f"Hem allowance included in pattern: {measurements.hem_allowance_cm} cm")

    if features.notes:
        lines.append(f"Pattern notes: {features.notes}")

    lines.append("")
    lines.append("Pattern pieces (use these exact names in your instructions):")
    for name in piece_names:
        lines.append(f"  • {name}")

    lines.append("")
    lines.append(
        "Write complete step-by-step sewing instructions for this garment. "
        "Include every step from pre-washing fabric to the final press. "
        "Explain techniques that a beginner may not know. "
        "Return only the JSON object described in the system prompt."
    )

    return "\n".join(lines)


def _parse_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines else []
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude returned invalid JSON: {raw_text[:300]}") from exc


async def generate_instructions(
    features: GarmentFeatures,
    measurements: Measurements,
    piece_names: list[str],
) -> dict:
    """Call Claude and return structured sewing instructions as a dict."""
    client = _get_client()
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    user_prompt = _build_user_prompt(features, measurements, piece_names)
    max_tokens = _compute_max_tokens(features, piece_names)
    logger.debug("Computed max_tokens=%d for %s with %d pieces", max_tokens, features.garment_type.value, len(piece_names))

    _RETRY_DELAYS = [3, 8, 15]
    raw_text = ""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw_text = response.content[0].text
            break
        except anthropic.AuthenticationError as exc:
            raise ValueError(
                "Anthropic API key is missing or invalid. Check your ANTHROPIC_API_KEY environment variable."
            ) from exc
        except anthropic.BadRequestError as exc:
            raise ValueError(f"Claude rejected the request: {exc}") from exc
        except anthropic.OverloadedError:
            if attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "Claude overloaded (attempt %d/%d), retrying in %ds…",
                    attempt + 1, len(_RETRY_DELAYS) + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise ValueError("Claude is temporarily overloaded. Please wait a moment and try again.")
        except anthropic.RateLimitError:
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            raise ValueError("Rate limit reached. Please wait a moment and try again.")
        except anthropic.APIError:
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            raise

    logger.debug("Instructions raw response length: %d chars", len(raw_text))
    if response.stop_reason == "max_tokens":
        raise ValueError(
            "Claude's response was cut off because the garment description produced too many "
            "instructions. Try reducing the number of pattern pieces or garment details."
        )
    return _parse_json_response(raw_text)
