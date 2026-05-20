from app.models.features import GarmentType

# Pocket disambiguation note appended to the system prompt for bottom garments.
# Helps the model choose the correct token when multiple pocket types are present.
_POCKET_NOTE = (
    "Pocket usage — include ALL pocket types visible, even when multiple apply:\n"
    "  'cargo_pocket'  = large utility pocket mounted on the thigh/hip with a button-down "
    "or velcro flap. Always include alongside 'patch_pockets' when cargo pockets are visible.\n"
    "  'patch_pockets' = any pocket applied flat to the outer fabric surface (chest, hip, back).\n"
    "  'welt_pockets'  = pocket with a fabric welt strip at the opening; no visible bag from outside.\n"
    "  'side_pockets'  = in-seam pockets whose bag is hidden inside the side seam.\n"
    "If you are uncertain, include the term that best describes what is visible; "
    "err toward specificity (cargo_pocket > patch_pockets)."
)

# Per-type vocabulary used in the dynamic system prompt
_GARMENT_VOCAB: dict[str, dict] = {
    "skirt": {
        "silhouettes": [
            "straight", "pencil", "a_line", "flared", "circle",
            "gathered", "pleated", "wrap", "trumpet", "mermaid", "tulip", "tiered",
        ],
        "length_categories": ["micro", "mini", "above_knee", "knee", "midi", "maxi"],
        "details": [
            "kick_pleat", "back_vent", "side_slits", "patch_pockets", "side_pockets",
            "welt_pockets", "belt_loops", "lining_visible", "topstitching",
            "ruffle", "elastic_waist",
        ],
        "has_waistband": True,
        "has_darts": True,
    },
    "dress": {
        "silhouettes": ["shift", "sheath", "a_line", "fit_and_flare", "wrap", "bodycon", "empire"],
        "sleeve_lengths": ["sleeveless", "spaghetti", "cap", "short", "three_quarter", "long"],
        "necklines": [
            "crew", "round", "scoop", "v_neck", "square", "boat",
            "sweetheart", "halter", "strapless", "off_shoulder",
        ],
        "length_categories": ["mini", "above_knee", "knee", "midi", "maxi"],
        "details": [
            "collar", "lining_visible", "topstitching",
            "spaghetti_straps", "straps", "halter_strap",
            "tie_back", "sash", "belt",
            "drawstring_waist", "elastic_waist", "smocking",
            "side_pockets", "patch_pockets",
            "ruffle", "pleats",
        ],
        "has_waistband": False,
        "has_darts": True,
    },
    "trousers": {
        "silhouettes": ["straight", "wide_leg", "tapered", "flared", "slim", "bootcut",
                        "skinny", "cigarette", "fitted", "regular", "relaxed", "palazzo"],
        "length_categories": ["full_length", "ankle", "cropped", "capri", "bermuda", "shorts"],
        "details": ["cuffs", "belt_loops", "patch_pockets", "welt_pockets", "side_pockets",
                    "pleats", "topstitching", "fly_shield", "cargo_pocket",
                    "high_rise", "low_rise", "ultra_high_rise"],
        "has_waistband": True,
        "has_darts": True,
    },
    "pants": {
        "silhouettes": ["straight", "wide_leg", "tapered", "flared", "slim", "jogger",
                        "palazzo", "bootcut", "fitted", "regular", "skinny"],
        "length_categories": ["full_length", "ankle", "cropped", "bermuda", "shorts"],
        "details": ["elastic_waist", "drawstring", "patch_pockets", "side_pockets",
                    "belt_loops", "topstitching", "cargo_pocket", "cuffs",
                    "welt_pockets", "high_rise", "low_rise"],
        "has_waistband": True,
        "has_darts": False,
    },
    "shirt": {
        "silhouettes": ["slim", "fitted", "regular", "relaxed", "boxy", "oversized", "athletic", "longline"],
        "sleeve_lengths": ["sleeveless", "cap", "short", "flutter", "three_quarter", "bell", "puff_short", "long", "puff_long"],
        "necklines": ["crew", "v_neck", "scoop", "round", "square", "polo", "mandarin", "boat", "turtleneck", "mock_turtleneck", "henley", "off_shoulder", "keyhole"],
        "length_categories": ["cropped", "hip_length", "tunic", "longline"],
        "details": ["collar", "ribbed_collar", "button_placket", "cuffs", "patch_pockets",
                    "chest_pocket", "topstitching", "yoke", "spaghetti_straps", "straps",
                    "drawstring_hem", "tie_front", "smocking", "elastic_hem"],
        "has_waistband": False,
        "has_darts": True,
    },
    "blouse": {
        "silhouettes": ["fitted", "relaxed", "peasant", "wrap", "peplum"],
        "sleeve_lengths": ["short", "long", "three_quarter", "sleeveless"],
        "necklines": ["crew", "v_neck", "round", "polo", "mandarin", "boat", "square"],
        "length_categories": ["cropped", "hip_length", "tunic"],
        "details": ["collar", "v_neck", "round_neck", "ruffles", "lining_visible", "topstitching",
                    "spaghetti_straps", "straps", "tie_front", "smocking", "elastic_hem"],
        "has_waistband": False,
        "has_darts": True,
    },
    "jacket": {
        "silhouettes": [
            # structured / tailored
            "fitted", "slim", "regular", "relaxed", "boxy", "oversized",
            # specialty
            "moto", "bomber", "military", "denim", "anorak", "varsity",
        ],
        "sleeve_lengths": ["short", "three_quarter", "long", "puff", "puff_short", "sleeveless"],
        "length_categories": ["waist_length", "cropped", "hip_length", "below_hip", "knee"],
        "details": [
            # structure / construction
            "collar", "notch_lapel", "peak_lapel", "shawl_collar", "band_collar", "no_collar",
            "lapels", "back_yoke", "yoke", "western_yoke",
            "facing", "lining_visible", "action_back",
            # closure / fastening
            "single_breasted", "double_breasted",
            "moto_zip", "asymmetric_zip", "center_zip", "snap_front",
            # pockets
            "patch_pockets", "welt_pockets", "side_pockets",
            "breast_pocket", "chest_pocket", "chest_welt", "in_seam_pockets", "slash_pockets",
            # surface finish
            "topstitching", "quilting", "embroidery",
            # outerwear details
            "hood", "epaulets", "epaulet_tab", "shoulder_tab",
            "belt", "belt_strap", "self_belt",
            "belt_loops", "drawstring_hem",
            # rib / knit trim (bomber / varsity / anorak)
            "cuff_band", "hem_band", "ribbed_cuffs", "ribbed_hem", "knit_cuffs", "knit_hem",
            # sleeve / cuff finishing
            "cuffs", "button_cuff", "snap_cuff", "woven_cuff",
            "sleeve_placket", "cuff_vent", "two_piece_sleeve", "tailored_sleeve",
        ],
        "has_waistband": False,
        "has_darts": True,
    },
    "blazer": {
        "silhouettes": ["fitted", "slim", "regular", "relaxed", "oversized", "boxy", "cropped"],
        "sleeve_lengths": ["short", "three_quarter", "long", "sleeveless"],
        "length_categories": ["cropped", "hip_length", "below_hip"],
        "details": [
            # lapel / collar
            "collar", "notch_lapel", "peak_lapel", "shawl_collar", "band_collar",
            # chest / fastening
            "single_breasted", "double_breasted",
            "facing", "lining_visible",
            # pockets
            "patch_pockets", "welt_pockets", "breast_pocket", "chest_welt", "in_seam_pockets",
            # construction
            "two_piece_sleeve", "tailored_sleeve", "back_yoke",
            # finish
            "topstitching", "sleeve_placket", "cuff_vent", "cuffs", "button_cuff",
        ],
        "has_waistband": False,
        "has_darts": True,
    },
    "bodice": {
        "silhouettes": ["fitted", "boned", "relaxed", "wrap"],
        "length_categories": ["cropped", "waist_length", "hip_length"],
        "details": ["boning", "lining_visible", "topstitching", "busk", "lace_up", "zipper"],
        "has_waistband": False,
        "has_darts": True,
    },
    "coat": {
        "silhouettes": ["a_line", "straight", "fitted", "wrap", "trench"],
        "length_categories": ["hip_length", "knee", "midi", "maxi"],
        "details": ["collar", "lapels", "patch_pockets", "welt_pockets", "lining_visible",
                    "topstitching", "belt", "hood", "double_breasted"],
        "has_waistband": False,
        "has_darts": True,
    },
    "shorts": {
        "silhouettes": ["straight", "fitted", "wide_leg", "bermuda", "bike"],
        "length_categories": ["micro", "short", "mid_thigh", "knee"],
        "details": ["belt_loops", "patch_pockets", "side_pockets", "cuffs",
                    "elastic_waist", "topstitching"],
        "has_waistband": True,
        "has_darts": False,
    },
}

# Fallback for any type not explicitly listed
_DEFAULT_VOCAB = {
    "silhouettes": ["fitted", "relaxed", "straight", "flared", "wrap"],
    "length_categories": ["short", "mid", "long"],
    "details": ["pockets", "lining_visible", "topstitching"],
    "has_waistband": False,
    "has_darts": False,
}


def build_system_prompt(garment_type: GarmentType) -> str:
    gtype = garment_type.value
    vocab = _GARMENT_VOCAB.get(gtype, _DEFAULT_VOCAB)

    waistband_line = (
        '3. waistband: { "type": "straight" | "contoured" | "elastic" | "facing" | "yoke",'
        ' "width_cm_estimate": number }\n'
        if vocab["has_waistband"]
        else '3. waistband: null\n'
    )
    darts_line = (
        '5. darts: { "front": number (0-4), "back": number (0-4) }\n'
        if vocab["has_darts"]
        else '5. darts: null\n'
    )

    sleeve_line = (
        f'7. sleeve_length: one of {vocab["sleeve_lengths"]}\n'
        if "sleeve_lengths" in vocab
        else ''
    )
    neckline_line = (
        f'8. neckline: one of {vocab["necklines"]}\n'
        if "necklines" in vocab
        else ''
    )
    confidence_num = 9 if (sleeve_line or neckline_line) else 7
    notes_num = confidence_num + 1

    pocket_note = (
        f'\n{_POCKET_NOTE}\n'
        if gtype in ("trousers", "pants", "shorts", "skirt", "dress")
        else ""
    )

    return (
        f'You are a garment analysis expert. Analyze the provided {gtype} photograph(s) '
        f'and return ONLY a JSON object with no additional text. Identify:\n\n'
        f'1. garment_type: "{gtype}"\n'
        f'2. silhouette: one of {vocab["silhouettes"]}\n'
        f'   length_category: one of {vocab["length_categories"]}\n'
        f'{waistband_line}'
        f'4. closure: {{"type": "center_back_zip" | "side_zip" | "button_fly" | "hook_and_eye" | "none",'
        f' "position": "center_back" | "left_side" | "right_side" | "center_front"}}\n'
        f'{darts_line}'
        f'6. details: array of strings from {vocab["details"]}\n'
        f'{pocket_note}'
        f'{sleeve_line}'
        f'{neckline_line}'
        f'{confidence_num}. confidence: number 0-1 representing overall confidence\n'
        f'{notes_num}. notes: string with any additional observations relevant to pattern making\n\n'
        f'If you cannot determine a feature, use your best judgment and note uncertainty in the '
        f'notes field. Respond with valid JSON only.'
    )


def build_user_prompt(garment_type: GarmentType) -> str:
    return f"Analyze this {garment_type.value} and return the structured JSON as specified."


# Static exports kept for backward compatibility with existing tests
SYSTEM_PROMPT = build_system_prompt(GarmentType.SKIRT)
USER_PROMPT = build_user_prompt(GarmentType.SKIRT)
