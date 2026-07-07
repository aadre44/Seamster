import logging

from app.debug_trace import trace_analyze
from app.llm import acomplete_with_retry, get_provider, parse_json_response
from app.models.features import (
    AsymmetryFeature,
    BindingFeature,
    Construction,
    GarmentFeatures,
    GarmentType,
    ShapeFeature,
)
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
    GarmentType.VEST,
}


# Keywords that indicate a patch pocket has a button-down or decorative flap.
# Only fires when patch_pockets is already present (or was just inferred).
_FLAP_KEYWORDS = ("flap", "flap detail", "button-down flap", "velcro flap", "snap flap")

# Pocket tokens that mean a flat applied pocket whose bottom shape matters.
_PATCH_POCKET_TOKENS = ("patch_pockets", "chest_pocket")
_POCKET_SHAPE_TOKENS = ("pocket_pointed", "pocket_rounded", "pocket_angled", "pocket_curved")

# Free-text phrases → pocket-shape token. Ordered most-specific first.
_NOTES_POCKET_SHAPE_MAP: list[tuple[str, str]] = [
    ("chevron",          "pocket_pointed"),
    ("pointed bottom",   "pocket_pointed"),
    ("comes to a point", "pocket_pointed"),
    ("v-shaped bottom",  "pocket_pointed"),
    ("v shaped bottom",  "pocket_pointed"),
    ("tapered bottom",   "pocket_pointed"),
    ("pointed",          "pocket_pointed"),
    ("chamfer",          "pocket_angled"),
    ("angled bottom",    "pocket_angled"),
    ("cut corner",       "pocket_angled"),
    ("hexagonal",        "pocket_angled"),
    ("u-shaped",         "pocket_curved"),
    ("u shaped",         "pocket_curved"),
    ("curved bottom",    "pocket_curved"),
    ("rounded bottom",   "pocket_rounded"),
    ("rounded corner",   "pocket_rounded"),
    ("rounded lower",    "pocket_rounded"),
]


def _infer_pockets_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Add pocket detail tokens inferred from free-text notes when the model missed them.

    Pocket-type inference (cargo/welt/in-seam) only fires for garment types where
    those make sense; flap and bottom-shape inference fire for ANY garment with a
    patch/chest pocket (shirts included — a tee can have a pointed chest pocket).
    Preserves all existing details and appends new ones without duplicating.
    """
    notes_lower = features.notes.lower()
    current = set(features.details)
    additions: list[str] = []

    if features.garment_type in _POCKET_INFERENCE_TYPES:
        for phrase, detail_key in _NOTES_POCKET_MAP:
            if phrase in notes_lower and detail_key not in current:
                current.add(detail_key)
                additions.append(detail_key)

    has_patch = any(t in current for t in _PATCH_POCKET_TOKENS)

    # If a patch pocket is present and notes describe a flap, add patch_pocket_flap
    # so the parametric engine generates the flap piece.
    if has_patch and "patch_pocket_flap" not in current:
        if any(kw in notes_lower for kw in _FLAP_KEYWORDS):
            current.add("patch_pocket_flap")
            additions.append("patch_pocket_flap")

    # Bottom-shape fallback: when a patch pocket is present but the model gave no
    # shape token, infer one from the notes (e.g. "comes to a point" → pointed).
    if has_patch and not any(t in current for t in _POCKET_SHAPE_TOKENS):
        for phrase, shape_key in _NOTES_POCKET_SHAPE_MAP:
            if phrase in notes_lower:
                current.add(shape_key)
                additions.append(shape_key)
                break

    if additions:
        logger.debug(
            "Inferred pocket details from notes for %s: %s",
            features.garment_type.value, additions,
        )
        features.details = list(features.details) + additions

    return features


# Garment types that have a construction topology (necklines / upper body).
_CONSTRUCTION_TYPES = {
    GarmentType.SHIRT, GarmentType.BLOUSE, GarmentType.DRESS, GarmentType.BODICE,
}


# Free-text → strap_width. Thin (skinny/spaghetti) vs wide (thick band / bust flares into).
_THIN_STRAP_SIGNALS = ("thin strap", "skinny strap", "spaghetti strap", "shoestring",
                       "string strap", "thin straps", "skinny straps")
_WIDE_STRAP_SIGNALS = ("wide strap", "thick strap", "broad strap", "wide straps",
                       "thick straps", "wide band", "flares into", "flare into",
                       "widens into", "gradual strap")


def _strap_width_from_notes(notes: str) -> str | None:
    """Return 'thin'/'wide' when the notes clearly describe the strap width, else None."""
    if any(s in notes for s in _WIDE_STRAP_SIGNALS):
        return "wide"
    if any(s in notes for s in _THIN_STRAP_SIGNALS):
        return "thin"
    return None


def _infer_construction_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Backfill ``construction`` from the neckline + free-text notes when the model
    left it null. Only fires for upper-body garments and never overrides an explicit
    object the model already returned.

    A halter top read as a plain shirt is the canonical miss this repairs: the notes
    describe "halter"/"backless"/"plunge" but the structured field was omitted.
    """
    if features.garment_type not in _CONSTRUCTION_TYPES:
        return features
    if features.construction is not None:
        return features

    notes = features.notes.lower()
    neckline = (features.neckline or "").lower()

    strap_style = "shoulder_seam"
    back_coverage = "full"
    front_opening = "closed"

    is_halter = neckline == "halter" or "halter" in notes
    if is_halter:
        strap_style = "halter_neck"
    elif neckline == "strapless" or "strapless" in notes:
        strap_style = "strapless"
    elif "spaghetti" in notes:
        strap_style = "spaghetti_straps"
    elif "one shoulder" in notes or "one-shoulder" in notes:
        strap_style = "one_shoulder"
    elif "racerback" in notes or "racer back" in notes:
        strap_style = "racerback"

    # Front opening first (it informs the back assumption below).
    if (
        "two front" in notes or "two panels" in notes
        or "split to the hem" in notes or "open to the hem" in notes
        or "open to the bottom" in notes or "down to the hem" in notes
    ):
        front_opening = "deep_v_split"
    elif any(p in notes for p in ("plunge", "plunging", "deep v", "deep-v",
                                  "open to the waist", "open front", "hang open")):
        front_opening = "plunge"
    elif neckline == "v_neck" and strap_style == "halter_neck":
        # A halter described as a deep V is a plunge on a single continuous front.
        front_opening = "plunge"
    elif "surplice" in notes or "wrap front" in notes or "crossover" in notes:
        front_opening = "surplice"
    elif "keyhole" in notes:
        front_opening = "keyhole"

    # Back coverage. Only call it backless on clear OBSERVED evidence (or a deep_v_split
    # front, which is typically backless); a merely *assumed* backless back (the model
    # guessing because the back is not visible) is discounted in favour of a covered
    # half back, since most halters cover the lower back.
    back_not_visible = (
        "not visible" in notes or "isn't visible" in notes or "cannot see the back" in notes
    )
    speculative = any(w in notes for w in (
        "assume", "assumed", "assuming", "likely", "presumab", "probably", "appears to be",
        "not visible",
    ))
    mentions_backless = any(
        p in notes for p in ("backless", "open back", "open-back", "bare back", "exposed back")
    )
    halterish = strap_style in ("halter_neck", "halter_tie", "strapless", "spaghetti_straps")
    if mentions_backless and not speculative:
        back_coverage = "backless"
    elif halterish and front_opening == "deep_v_split":
        back_coverage = "backless"
    elif "low back" in notes or "low-back" in notes or "scooped back" in notes or "half back" in notes:
        back_coverage = "low_back"
    elif "racerback" in notes or "racer back" in notes:
        back_coverage = "racer"
    elif halterish and (back_not_visible or mentions_backless):
        # halter with an unseen / only-assumed-open back → conservative covered half back
        back_coverage = "low_back"

    if (strap_style, back_coverage, front_opening) == ("shoulder_seam", "full", "closed"):
        return features  # nothing notable inferred — leave construction null

    features.construction = Construction(
        strap_style=strap_style,
        back_coverage=back_coverage,
        front_opening=front_opening,
        strap_width=_strap_width_from_notes(notes),
    )
    logger.debug(
        "Inferred construction for %s: %s", features.garment_type.value, features.construction
    )
    return features


def _refine_strap_width(features: GarmentFeatures) -> GarmentFeatures:
    """Backfill strap_width from the notes when the model returned a construction but left
    strap_width null. Leaves an explicit value alone. Generator falls back to a per-style
    default when it stays None.
    """
    c = features.construction
    if features.garment_type not in _CONSTRUCTION_TYPES or c is None or c.strap_width is not None:
        return features
    inferred = _strap_width_from_notes(features.notes.lower())
    if inferred is not None:
        c.strap_width = inferred
        logger.debug("Inferred strap_width=%s from notes for %s", inferred, features.garment_type.value)
    return features


# Free-text signals that the centre front is genuinely SPLIT (two separate panels with
# an open gap), not just a deep V notch on one continuous panel. Distinguishing these from
# a photo is hard, so a `plunge` is upgraded to `deep_v_split` when the notes describe the
# panels as open/separate/loose — even when the model already returned a construction.
_SPLIT_FRONT_SIGNALS = (
    "open/loose", "open at the cent", "panels appear to be open", "panels are open",
    "panels open", "two panels", "two front panels", "hang open", "hangs open",
    "hanging open", "not connected", "not joined", "do not meet", "don't meet",
    "doesn't meet", "separate panel", "separate front", "open down the front",
    "open down the cent", "split down", "gap at the cent", "gap between the",
)


def _refine_front_split(features: GarmentFeatures) -> GarmentFeatures:
    """Upgrade a `plunge` (or `closed`) front to `deep_v_split` when the notes clearly
    describe the front panels as open/separate at the centre. The split — front open down
    the middle, panels joined only by the strap — is a defining design detail the vision
    model frequently mislabels as a continuous plunge. Only fires on explicit separation
    language so a true continuous plunge is left alone; back coverage is untouched.
    """
    c = features.construction
    if features.garment_type not in _CONSTRUCTION_TYPES or c is None:
        return features
    if c.front_opening not in ("plunge", "closed"):
        return features
    if any(sig in features.notes.lower() for sig in _SPLIT_FRONT_SIGNALS):
        c.front_opening = "deep_v_split"
        logger.debug(
            "Refined front_opening → deep_v_split from notes for %s", features.garment_type.value
        )
    return features


# A halter is supported AT THE NECK (left+right straps connect behind/around the neck, bare
# shoulders). A tank/cami is supported AT THE SHOULDERS (straps over the shoulders). The model
# over-applies `halter_neck` to any thin-strap sleeveless top, so we only KEEP a halter when
# the notes give positive neck-support evidence; otherwise it is a tank ("when unsure → tank").
_TANK_SIGNALS = ("tank top", "tank-top", "tanktop", "camisole", "cami top", " cami,",
                 "spaghetti")
_OVER_SHOULDER_SIGNALS = ("over the shoulder", "over each shoulder", "on the shoulder",
                          "shoulder strap", "straps over the", "atop the shoulder")
# Positive evidence that the top is genuinely anchored at the neck (a real halter).
_HALTER_EVIDENCE = (
    "behind the neck", "around the neck", "at the neck", "to the neck", "round the neck",
    "back of the neck", "neck strap", "neckstrap", "halter neck", "halterneck",
    "ties behind", "tie behind", "tied behind", "loop behind", "loops behind",
    "bare shoulder", "shoulders are bare", "shoulders bare", "exposed shoulder",
)


def _refine_strap_style(features: GarmentFeatures) -> GarmentFeatures:
    """Keep `halter_neck`/`halter_tie` only when the garment is genuinely anchored at the NECK;
    otherwise downgrade to `spaghetti_straps`. A halter's left+right straps connect behind the
    neck (bare shoulders); a tank's straps pass over the shoulders. The model frequently calls
    any thin-strap sleeveless top a halter, so:
      - explicit tank/cami or over-shoulder language ⇒ tank (spaghetti_straps);
      - otherwise REQUIRE positive neck-support evidence to keep the halter; with none, it is a
        tank ("when unsure → tank").
    Skipped when the neckline is explicitly 'halter' (a confident, explicit signal).
    """
    c = features.construction
    if features.garment_type not in _CONSTRUCTION_TYPES or c is None:
        return features
    if c.strap_style not in ("halter_neck", "halter_tie"):
        return features
    if (features.neckline or "").lower() == "halter":
        return features  # the model explicitly chose a halter neckline — trust it
    notes = features.notes.lower()
    tankish = any(s in notes for s in _TANK_SIGNALS) or any(s in notes for s in _OVER_SHOULDER_SIGNALS)
    has_neck_evidence = any(s in notes for s in _HALTER_EVIDENCE)
    if tankish or not has_neck_evidence:
        c.strap_style = "spaghetti_straps"
        logger.debug(
            "Refined halter → spaghetti_straps (%s) for %s",
            "tank/over-shoulder language" if tankish else "no neck-support evidence",
            features.garment_type.value,
        )
    return features


def _clamp_spaghetti_back(features: GarmentFeatures) -> GarmentFeatures:
    """A spaghetti-strap top cannot have a FULL back — thin straps can only hold up a half
    back at most (or a backless one). Clamp back_coverage='full' to 'low_back'; leave
    'backless' / 'low_back' / 'racer' as they are.
    """
    c = features.construction
    if features.garment_type not in _CONSTRUCTION_TYPES or c is None:
        return features
    if c.strap_style == "spaghetti_straps" and c.back_coverage == "full":
        c.back_coverage = "low_back"
        logger.debug(
            "Clamped spaghetti-strap back_coverage full → low_back for %s",
            features.garment_type.value,
        )
    return features


# Free-text → binding edge. A vest's signature contrast trim is frequently described in
# the notes even when the model omits the structured `binding` object.
_BINDING_SIGNALS = (
    "binding", "bound edge", "bound neckline", "piping", "contrast trim", "contrast edge",
    "contrast tape", "bias tape", "trim around the neck", "trimmed in", "edged in",
)


def _infer_vest_finishes_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Backfill a vest's binding/facings from free-text notes when the model omitted them.

    The contrast neckline binding is the defining detail of many vests, but the model often
    only mentions it in the notes. When binding language is present and no structured
    ``binding`` was returned, attach a neckline binding (contrast inferred from the wording).
    Never overrides an explicit object the model already returned.
    """
    if features.garment_type != GarmentType.VEST:
        return features

    notes = features.notes.lower()
    if features.binding is None and any(s in notes for s in _BINDING_SIGNALS):
        edges: list[str] = ["neckline"]
        if "armhole" in notes and ("bound" in notes or "bind" in notes or "trim" in notes):
            edges.append("armhole")
        contrast = not any(s in notes for s in ("self-binding", "self binding", "tonal", "same fabric"))
        features.binding = BindingFeature(edges=edges, width_cm=1.0, contrast=contrast)
        logger.debug("Inferred vest binding from notes: %s", features.binding)

    # A clean sleeveless armhole with no binding is almost always faced.
    if (
        "armhole" not in features.facings
        and (features.binding is None or "armhole" not in features.binding.edges)
        and any(s in notes for s in ("faced armhole", "armhole facing", "clean armhole", "faced edge"))
    ):
        features.facings = list(features.facings) + ["armhole"]

    return features


# Garment types that carry a structured shape/contour (vest / bodice).
_SHAPE_TYPES = {GarmentType.VEST, GarmentType.BODICE}

# Free-text → hem_style. Ordered most-specific first.
_NOTES_HEM_MAP: list[tuple[str, str]] = [
    ("cutaway", "cutaway"),
    ("cut away", "cutaway"),
    ("open front hem", "cutaway"),
    ("rounded front", "cutaway"),
    ("high-low", "high_low"),
    ("high low", "high_low"),
    ("hi-low", "high_low"),
    ("mullet hem", "high_low"),
    ("pointed hem", "pointed"),
    ("points at the cent", "pointed"),
    ("v hem", "pointed"),
    ("v-hem", "pointed"),
    ("comes to a point", "pointed"),
    ("scoop", "curved_scoop"),
    ("curved hem", "curved_scoop"),
    ("rounded hem", "curved_scoop"),
    ("angled hem", "angled"),
    ("diagonal hem", "angled"),
]

_SWING_SIGNALS = ("swing", "flared hem", "a-line", "a line", "sweeps out", "flares out")
_PEG_SIGNALS = ("tapered hem", "pegged", "narrows at the hem", "tapers in")
_VENT_SIGNALS = ("side vent", "side vents", "side slit", "side slits", "vents at the hem",
                 "slits at the hem", "open slit", "open slits", "vented hem")
# Open/cutaway front (panels do NOT meet). Wrap/surplice OVERLAP is deliberately excluded.
_CUTAWAY_SIGNALS = ("cutaway", "cut away", "cut-away", "rounded open front", "waistcoat front")
_OPEN_DRAPE_SIGNALS = ("open front", "hangs open", "panels separate", "panels do not meet",
                       "open down the front", "draped open", "centre front is open",
                       "center front is open")


def _infer_shape_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Backfill a vest/bodice ``shape`` from free-text notes when the model omitted it.

    The silhouette/contour is the design feature the user cares most about, but the model
    often only describes it in prose. Never overrides an explicit object the model returned.
    """
    if features.garment_type not in _SHAPE_TYPES or features.shape is not None:
        return features

    notes = features.notes.lower()
    hem_style = "straight"
    for phrase, style in _NOTES_HEM_MAP:
        if phrase in notes:
            hem_style = style
            break

    hem_sweep = 0.0
    if any(s in notes for s in _SWING_SIGNALS):
        hem_sweep = 6.0
    elif any(s in notes for s in _PEG_SIGNALS):
        hem_sweep = -4.0

    side_vent = 8.0 if any(s in notes for s in _VENT_SIGNALS) else 0.0

    front_cut = "closed"
    front_cut_depth = 0.0
    if any(s in notes for s in _CUTAWAY_SIGNALS):
        front_cut, front_cut_depth = "cutaway", 8.0
    elif any(s in notes for s in _OPEN_DRAPE_SIGNALS):
        front_cut, front_cut_depth = "open_drape", 10.0

    if (hem_style == "straight" and hem_sweep == 0.0
            and side_vent == 0.0 and front_cut == "closed"):
        return features  # nothing notable inferred — leave shape null

    depth = 4.0 if hem_style in ("pointed", "curved_scoop", "cutaway") else 0.0
    high_low = 5.0 if hem_style == "high_low" else 0.0
    features.shape = ShapeFeature(
        hem_style=hem_style, hem_depth_cm=depth, hem_sweep_cm=hem_sweep, high_low_cm=high_low,
        side_vent_cm=side_vent, front_cut=front_cut, front_cut_depth_cm=front_cut_depth,
    )
    logger.debug("Inferred shape for %s: %s", features.garment_type.value, features.shape)
    return features


# Free-text signals for an asymmetric diagonal wrap front (the two fronts are DIFFERENT panels).
# An evenly-overlapped wrap/surplice that is symmetric is excluded.
_ASYMMETRIC_SIGNALS = (
    "asymmetric", "asymmetrical", "wrap-over", "wrap over", "wraps over", "crosses from",
    "crosses over", "diagonal closure", "diagonal front", "diagonal hem", "off to one side",
    "off-centre", "off center", "one side", "angled overlap", "crossed over to",
)
_MANDARIN_SIGNALS = ("mandarin collar", "mandarin", "stand collar", "standing collar",
                     "band collar", "tang collar", "chinese collar")


def _infer_asymmetry_from_notes(features: GarmentFeatures) -> GarmentFeatures:
    """Backfill an asymmetric wrap front + mandarin collar for a vest/bodice from the notes.

    The structured fields can only express symmetric fronts, so the model frequently records a
    diagonal wrap only in prose. Sets ``asymmetry`` and adds a ``mandarin_collar`` detail token
    when the notes describe them. Never overrides an explicit asymmetry object.
    """
    if features.garment_type not in _SHAPE_TYPES:
        return features
    notes = features.notes.lower()

    if features.asymmetry is None and any(s in notes for s in _ASYMMETRIC_SIGNALS):
        wrap_side = "left" if ("to the left" in notes or "left side" in notes) else "right"
        features.asymmetry = AsymmetryFeature(
            front_style="asymmetric_wrap", wrap_side=wrap_side, overlap_cm=14.0, closure_drop_frac=1.0,
        )
        logger.debug("Inferred asymmetric wrap front for %s: %s", features.garment_type.value, features.asymmetry)

    if any(s in notes for s in _MANDARIN_SIGNALS) and "mandarin_collar" not in features.details:
        features.details = list(features.details) + ["mandarin_collar"]

    return features


async def analyze_garment(
    garment_type: GarmentType,
    front_bytes: bytes,
    back_bytes: bytes | None = None,
    force_contours: bool = False,
) -> GarmentFeatures:
    """Call the configured LLM's vision API and return structured features for any garment type.

    ``force_contours`` (dev/testing) makes the prompt demand a piece_contours entry
    for EVERY visible piece so the contour-patternizing path can be exercised on
    photos where the vocabulary would normally cover everything."""
    system_prompt = build_system_prompt(garment_type, force_contours=force_contours)
    user_prompt = build_user_prompt(garment_type)
    trace_request = {
        "garment_type": garment_type.value,
        "force_contours": force_contours,
        "front_image_bytes": len(front_bytes),
        "back_image_bytes": len(back_bytes) if back_bytes else None,
    }
    raw_text: str | None = None

    try:
        images = [front_bytes] if back_bytes is None else [front_bytes, back_bytes]
        # Constrained decoding (Ollama) + deterministic temperature curb the
        # out-of-enum closures and hallucinated details a small local model emits.
        # The schema is ignored by providers that don't support it (Anthropic).
        # 8192 tokens: a forced-contour analysis enumerates every piece with a
        # 4-16 point outline — 2048 used to cut those responses off mid-JSON.
        response = await acomplete_with_retry(
            get_provider(),
            system=system_prompt,
            user_text=user_prompt,
            max_tokens=8192,
            images=images,
            response_format=GarmentFeatures.model_json_schema(),
            temperature=0,
        )
        raw_text = response.text

        logger.debug("LLM raw response: %s", raw_text[:500])
        try:
            data = parse_json_response(raw_text)
        except ValueError as exc:
            if response.truncated:
                raise ValueError(
                    "The vision model's response was cut off at the token limit before the "
                    "JSON was complete. Try again; if it persists, raise the analyzer max_tokens."
                ) from exc
            raise

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
            raise ValueError(
                f"Could not parse the LLM's response into garment features: {exc}"
            ) from exc

        features = _infer_pockets_from_notes(features)
        features = _infer_construction_from_notes(features)
        features = _refine_front_split(features)
        features = _refine_strap_style(features)
        features = _clamp_spaghetti_back(features)
        features = _refine_strap_width(features)
        features = _infer_vest_finishes_from_notes(features)
        features = _infer_shape_from_notes(features)
        features = _infer_asymmetry_from_notes(features)
    except Exception as exc:
        trace_analyze(
            trace_request, system_prompt, user_prompt, raw_text,
            features=None, error=str(exc),
        )
        raise

    trace_analyze(
        trace_request, system_prompt, user_prompt, raw_text,
        features=features.model_dump(mode="json"),
    )
    return features
