import asyncio
import base64
import json
import logging
import os

import anthropic

from app.models.features import GarmentFeatures, GarmentType, SkirtFeatures
from app.vision.prompts import SYSTEM_PROMPT, USER_PROMPT, build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _media_type(img_bytes: bytes) -> str:
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:4] == b"GIF8":
        return "image/gif"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # default / JPEG magic \xff\xd8


def _build_content(front_bytes: bytes, back_bytes: bytes | None, user_prompt: str) -> list:
    images = [front_bytes] if back_bytes is None else [front_bytes, back_bytes]
    content: list = []
    for img_bytes in images:
        b64 = base64.standard_b64encode(img_bytes).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _media_type(img_bytes), "data": b64},
        })
    content.append({"type": "text", "text": user_prompt})
    return content


async def _call_claude(system_prompt: str, user_prompt: str, front_bytes: bytes, back_bytes: bytes | None) -> str:
    client = _get_client()
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_content(front_bytes, back_bytes, user_prompt)}],
    )
    return response.content[0].text


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
        raise ValueError(f"Claude returned invalid JSON: {raw_text[:200]}") from exc


# Keyword phrases in the notes that indicate a specific pocket type which the
# vision model may have omitted from the structured `details` list.
# Ordered from most-specific to least so earlier matches win.
_NOTES_POCKET_MAP: list[tuple[str, str]] = [
    ("cargo pocket",       "cargo_pocket"),
    ("cargo pockets",      "cargo_pocket"),
    ("flap pocket",        "cargo_pocket"),
    ("bellows pocket",     "cargo_pocket"),
    ("bellows pockets",    "cargo_pocket"),
    ("thigh pocket",       "cargo_pocket"),
    ("thigh pockets",      "cargo_pocket"),
    ("welt pocket",        "welt_pockets"),
    ("welt pockets",       "welt_pockets"),
    ("jetted pocket",      "welt_pockets"),
    ("in-seam pocket",     "side_pockets"),
    ("slash pocket",       "side_pockets"),
    ("slash pockets",      "side_pockets"),
    ("inseam pocket",      "side_pockets"),
]

# Garment types for which notes-based pocket inference is applicable
_POCKET_INFERENCE_TYPES = {
    GarmentType.PANTS, GarmentType.TROUSERS,
    GarmentType.SHORTS, GarmentType.SKIRT, GarmentType.DRESS,
    GarmentType.JACKET, GarmentType.COAT, GarmentType.BLAZER,
}


# Keywords that indicate a patch pocket has a button-down or decorative flap.
# Only fires when patch_pockets is already present (or was just inferred).
_FLAP_KEYWORDS = ("flap", "flap detail", "button-down flap", "velcro flap", "snap flap")


def _infer_pockets_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Add pocket detail tokens inferred from free-text notes when the model missed them.

    Only fires for garment types where pocket inference makes sense.
    Preserves all existing details and appends new ones without duplicating.
    """
    if features.garment_type not in _POCKET_INFERENCE_TYPES:
        return features

    notes_lower = features.notes.lower()
    current = set(features.details)
    additions: list[str] = []

    for phrase, detail_key in _NOTES_POCKET_MAP:
        if phrase in notes_lower and detail_key not in current:
            current.add(detail_key)
            additions.append(detail_key)

    # If patch_pockets are present (or just inferred) and notes describe a flap,
    # add patch_pocket_flap so the parametric engine generates the flap piece.
    if "patch_pockets" in current and "patch_pocket_flap" not in current:
        if any(kw in notes_lower for kw in _FLAP_KEYWORDS):
            current.add("patch_pocket_flap")
            additions.append("patch_pocket_flap")

    if additions:
        logger.debug(
            "Inferred pocket details from notes for %s: %s",
            features.garment_type.value, additions,
        )
        features.details = list(features.details) + additions

    return features


async def analyze_garment(
    garment_type: GarmentType,
    front_bytes: bytes,
    back_bytes: bytes | None = None,
) -> GarmentFeatures:
    """Call Claude vision API and return structured features for any garment type."""
    system_prompt = build_system_prompt(garment_type)
    user_prompt = build_user_prompt(garment_type)

    # Retry schedule: overloaded errors get longer waits; rate-limit errors get shorter ones.
    _RETRY_DELAYS = [3, 8, 15]  # seconds before each successive attempt
    raw_text = ""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            raw_text = await _call_claude(system_prompt, user_prompt, front_bytes, back_bytes)
            break
        except anthropic.AuthenticationError as exc:
            raise ValueError("Anthropic API key is missing or invalid. Check your ANTHROPIC_API_KEY environment variable.") from exc
        except anthropic.BadRequestError as exc:
            raise ValueError(f"Claude rejected the request: {exc}") from exc
        except anthropic.OverloadedError:
            if attempt < len(_RETRY_DELAYS):
                delay = _RETRY_DELAYS[attempt]
                logger.warning("Claude overloaded (attempt %d/%d), retrying in %ds…", attempt + 1, len(_RETRY_DELAYS) + 1, delay)
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

    logger.debug("Claude raw response: %s", raw_text[:500])
    data = _parse_json_response(raw_text)

    notes: str = data.get("notes", "")
    gtype = garment_type.value
    if f"no {gtype}" in notes.lower() or "cannot identify" in notes.lower():
        raise ValueError(
            f"We couldn't identify a {gtype} in this photo. "
            f"Please upload a clear front-view photo of a {gtype}."
        )

    data["garment_type"] = gtype
    try:
        features = GarmentFeatures.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Could not parse Claude's response into garment features: {exc}") from exc

    features = _infer_pockets_from_notes(features)
    return features


async def analyze_skirt(front_bytes: bytes, back_bytes: bytes | None = None) -> SkirtFeatures:
    """Backward-compatible wrapper — calls analyze_garment and narrows to SkirtFeatures."""
    _RETRY_DELAYS = [3, 8, 15]
    raw_text = ""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            raw_text = await _call_claude(SYSTEM_PROMPT, USER_PROMPT, front_bytes, back_bytes)
            break
        except anthropic.AuthenticationError as exc:
            raise ValueError("Anthropic API key is missing or invalid.") from exc
        except anthropic.BadRequestError as exc:
            raise ValueError(f"Claude rejected the request: {exc}") from exc
        except anthropic.OverloadedError:
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            raise ValueError("Claude is temporarily overloaded. Please try again.")
        except (anthropic.RateLimitError, anthropic.APIError):
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            raise

    logger.debug("Claude raw response: %s", raw_text[:500])
    data = _parse_json_response(raw_text)

    notes: str = data.get("notes", "")
    if "no skirt" in notes.lower() or "cannot identify" in notes.lower():
        raise ValueError(
            "We couldn't identify a skirt in this photo. "
            "Please upload a clear front-view photo of a skirt."
        )

    return SkirtFeatures.model_validate(data)
