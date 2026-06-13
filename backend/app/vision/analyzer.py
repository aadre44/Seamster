import logging

from app.llm import acomplete_with_retry, get_provider, parse_json_response
from app.models.features import GarmentFeatures, GarmentType
from app.vision.prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


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
    """Call the configured LLM's vision API and return structured features for any garment type."""
    system_prompt = build_system_prompt(garment_type)
    user_prompt = build_user_prompt(garment_type)

    images = [front_bytes] if back_bytes is None else [front_bytes, back_bytes]
    # Constrained decoding (Ollama) + deterministic temperature curb the
    # out-of-enum closures and hallucinated details a small local model emits.
    # The schema is ignored by providers that don't support it (Anthropic).
    response = await acomplete_with_retry(
        get_provider(),
        system=system_prompt,
        user_text=user_prompt,
        max_tokens=2048,
        images=images,
        response_format=GarmentFeatures.model_json_schema(),
        temperature=0,
    )
    raw_text = response.text

    logger.debug("LLM raw response: %s", raw_text[:500])
    data = parse_json_response(raw_text)

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
        raise ValueError(f"Could not parse the LLM's response into garment features: {exc}") from exc

    features = _infer_pockets_from_notes(features)
    return features
