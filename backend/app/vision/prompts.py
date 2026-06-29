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

# Pocket-shape tokens — the model appends ONE when a patch/chest pocket is visible
# so the engine can build the correct bottom edge instead of a plain rectangle.
_POCKET_SHAPE_TOKENS = ["pocket_pointed", "pocket_rounded", "pocket_angled", "pocket_curved"]

_POCKET_SHAPE_NOTE = (
    "Pocket bottom shape — when a patch or chest pocket is visible, ALSO append ONE "
    "shape token describing its lower edge (omit if it is a plain square pocket):\n"
    "  'pocket_pointed' = bottom comes to a downward point / chevron / V at the centre.\n"
    "  'pocket_rounded' = square bottom with softly rounded lower corners.\n"
    "  'pocket_angled'  = bottom corners cut off at 45 degrees (chamfered / hexagonal look).\n"
    "  'pocket_curved'  = whole bottom edge is a smooth U-shaped curve.\n"
    "Look closely: heritage/streetwear chest pockets are frequently pointed, not square."
)

# Pleat taxonomy appended to the system prompt for any garment that can be pleated.
_PLEAT_NOTE = (
    "Pleat types: 'knife' = all folds pressed the same direction; 'box' = two folds "
    "turned away from each other forming a raised panel; 'inverted_box' = two folds "
    "turned toward each other meeting at a centre line; 'accordion' = even narrow "
    "zig-zag folds; 'pintuck' = rows of tiny stitched tucks. Estimate count across the "
    "garment, where they sit, and the approximate finished depth of each fold in cm."
)

# Construction-topology taxonomy appended for upper-body garments (those with
# necklines). Captures three orthogonal axes the neckline/details model can't express:
# how the garment is held up, how much back it has, and the centre-front treatment.
_CONSTRUCTION_NOTE = (
    "Construction axes — describe HOW the garment is built, independently of the neckline:\n"
    "  strap_style (defined by the ANCHOR POINT — what physically holds the top up): "
    "'shoulder_seam' = ordinary garment seamed over the shoulders (has sleeves or cap "
    "shoulders); 'halter_neck' = anchored at the NECK — the left and right straps connect to "
    "EACH OTHER behind the neck (the neck holds the top up), so NOTHING crosses the shoulders "
    "and the shoulders are bare; 'halter_tie' = same, finished as ties; 'spaghetti_straps' = "
    "anchored at the SHOULDERS — thin straps connect the FRONT to the BACK over each shoulder "
    "(a tank/cami); 'wide_straps' = same but wide straps; 'one_shoulder' = a single asymmetric "
    "strap over one shoulder; 'strapless' = no straps at all; 'racerback' = shoulder straps "
    "that converge to a narrow back.\n"
    "  back_coverage: 'full' = normal full back; 'low_back' = back scoops low; "
    "'backless' = open back, no back panel; 'racer' = narrow racer back.\n"
    "  strap_width (how wide the strap looks relative to the body — applies to halter straps "
    "AND spaghetti/wide straps): 'thin' = skinny/spaghetti (~1-2 cm); 'medium' = a moderate "
    "strap (~3-4 cm); 'wide' = a thick band the bodice flares into (~5-8 cm). Use null only if "
    "you truly cannot tell. A halter whose bust panel widens smoothly into a broad strap is "
    "'wide'; a skinny shoestring strap is 'thin'.\n"
    "  front_opening: 'closed' = closed centre front; 'plunge' = deep V/U on a SINGLE "
    "continuous front (the V is just an opening, the fabric is continuous below it — it does "
    "NOT divide the front into two pieces); 'deep_v_split' = the centre front is open all the "
    "way down so the front is two separate panels joined only by the straps; 'keyhole' = small "
    "CF cut-out; 'surplice' = crossed wrap; 'placket' = buttoned placket; 'wrap' = wrap-over.\n"
    "CRITICAL — sleeves & shoulders: if the garment is held up by straps or a halter (any "
    "strap_style other than 'shoulder_seam'), it is SLEEVELESS (sleeve_length='sleeveless') and "
    "has NO shoulder seam. When the shoulders are bare and the top is held by straps/a halter, "
    "set strap_style accordingly and sleeve_length='sleeveless' — never report such a top as a "
    "plain shoulder_seam blouse with sleeves.\n"
    "DECISION — halter vs tank, decided ONLY by the support/anchor point (do NOT default to "
    "halter just because a top is sleeveless with thin straps):\n"
    "  • A HALTER is supported at the NECK: the left and right straps connect to each other "
    "behind/around the neck and the neck holds the top up. Therefore NOTHING crosses the "
    "shoulders — the tops of the shoulders are BARE and the straps angle inward toward the "
    "throat. → 'halter_neck'.\n"
    "  • A TANK/CAMI is supported at the SHOULDERS: each strap runs OVER the top of a shoulder, "
    "connecting the front to the back; the shoulders bear the weight. You can see a strap lying "
    "on each shoulder. → 'spaghetti_straps' (thin) or 'wide_straps' (wide).\n"
    "So: straps lying OVER the shoulders = tank (spaghetti/wide). Straps that meet at the neck "
    "with BARE shoulders = halter. If you can see a strap on top of either shoulder, it is NOT a "
    "halter. A scoop/round/square-neck cami with two shoulder straps is a tank. When unsure, "
    "choose 'spaghetti_straps', not 'halter_neck'. 'strapless' = a bare top edge, no straps.\n"
    "Choosing plunge vs deep_v_split (look carefully — this is easy to miss): if you can see "
    "skin/body BETWEEN two separate front panels, or the two front edges are loose/open/do "
    "not meet, or the front is a tie-front / wrap that knots or crosses at the centre, it is "
    "'deep_v_split' (the panels are joined only by the straps, NOT by fabric across the "
    "centre). Use 'plunge' only when the fabric is clearly ONE unbroken panel with a V cut "
    "into it. A halter or tie-front top whose centre hangs open is 'deep_v_split', not "
    "'plunge'. Do not describe a top as a 'single continuous front' if its centre is open.\n"
    "Choosing back_coverage when the back is NOT visible: most halter/strappy tops have a "
    "COVERED lower back, so prefer 'low_back' (a half back to the shoulder blades, bare "
    "shoulders). Use 'backless' only when the back is clearly open/bare, or when the front is a "
    "deep_v_split (such tops are typically backless). Never assume 'backless' from a halter neck "
    "alone.\n"
    "A spaghetti-strap or thin-strap top CANNOT have a full back — its back_coverage is at most "
    "'low_back' (a half back), or 'backless'. Never use 'full' for a spaghetti-strap top."
)

# Edge-finish taxonomy appended for garments that can carry bindings / facings / welt
# pockets (vests). Captures the bound-edge trim and faced openings the neckline / details
# fields cannot express on their own.
_EDGE_FINISH_NOTE = (
    "Edge finishes — describe how the neckline, armholes and hem are FINISHED:\n"
    "  binding: a continuous narrow strip wrapping a raw edge and showing as a thin lip on the "
    "right side, often in a CONTRAST colour/fabric (the signature dark trim around a neckline). "
    "List every edge it runs along (neckline / armhole / hem), its finished width in cm, and "
    "whether it is a contrast colour. Use null when no binding is visible.\n"
    "  facings: edges finished by a facing turned fully to the INSIDE (no visible trim) — list "
    "any of neckline / armhole / hem. A clean sleeveless armhole with no topstitched lip is "
    "usually faced. Empty array when none.\n"
    "  welt_pockets: bound/besom pockets set INTO the garment (a fabric lip at the opening, no "
    "patch visible). For each, give position (lower_front / chest / side_front / back), the "
    "opening width in cm, how many appear (count), and besom=true for a double-lip besom. "
    "Empty array when there are none.\n"
    "Necklines: 'notched_v' = a short narrow vertical slit at centre-front that steps out "
    "through a small NOTCH into a V (a collarless lapel-notch look); 'split_v' = the same narrow "
    "CF slit flaring into a clean V without the notch step. Use these (not plain 'v_neck') when "
    "the centre front has a distinct slit/notch."
)

# Silhouette/contour taxonomy appended for shape-aware garments (vest / bodice). Captures the
# hem contour and body taper that the fit-style alone cannot express.
_SHAPE_NOTE = (
    "Garment shape — describe the CONTOUR of the body, separately from fit:\n"
    "  hem_style: the shape of the bottom edge — 'straight' (flat), 'pointed' (drops to a "
    "centre-front point / V hem, like a waistcoat), 'angled' (straight diagonal up toward the "
    "side), 'curved_scoop' (smooth curved hem), 'high_low' (front and back/side hems at "
    "different heights), 'cutaway' (the centre-front hem corner is rounded away / open).\n"
    "  hem_depth_cm: how far the point/scoop deviates from a flat hem (cm).\n"
    "  waist_taper_cm: how much the side seam nips in at the waist (cm; 0 = straight/boxy).\n"
    "  hem_sweep_cm: how much the hem flares out (+) or pegs in (−) at the side seam (cm).\n"
    "  high_low_cm: for high_low, the signed front-minus-side hem height difference (cm).\n"
    "  side_vent_cm: if the lower SIDE SEAM is left open as a vent/slit, how tall it is (cm); "
    "0 if there is no side vent.\n"
    "  front_cut: how the two fronts meet BELOW the closure — 'closed' (they meet or overlap, "
    "including a wrap/surplice), 'cutaway' (the lower centre-front curves away so the hem opens, "
    "like a waistcoat), 'open_drape' (the centre-front hangs open from high up to the hem, the "
    "panels clearly separate).\n"
    "  front_cut_depth_cm: for cutaway/open_drape, how far each front swings away from the "
    "centre at the hem (cm).\n"
    "Look at the SILHOUETTE: a boxy vest is straight; a waistcoat points or cuts away at the "
    "centre front; a swing vest sweeps out at the hem; many vests have short side vents. Note: a "
    "WRAP/SURPLICE front where the panels OVERLAP is 'closed', not a cutaway (cutaway/open_drape "
    "mean the fronts do NOT meet)."
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
        "closures": ["center_back_zip", "side_zip", "button_front", "hook_and_eye", "none"],
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
        "closures": ["center_back_zip", "side_zip", "button_front", "none"],
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
        "closures": ["button_fly", "side_zip", "none"],
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
        "closures": ["button_fly", "side_zip", "none"],
        "has_waistband": True,
        "has_darts": False,
    },
    "shirt": {
        "silhouettes": ["slim", "fitted", "regular", "relaxed", "boxy", "oversized", "athletic", "longline"],
        "sleeve_lengths": ["sleeveless", "cap", "short", "flutter", "three_quarter", "bell", "puff_short", "long", "puff_long"],
        "necklines": ["crew", "v_neck", "scoop", "round", "square", "polo", "mandarin", "boat", "turtleneck", "mock_turtleneck", "henley", "off_shoulder", "keyhole", "halter", "strapless"],
        "length_categories": ["cropped", "hip_length", "tunic", "longline"],
        "details": ["collar", "ribbed_collar", "button_placket", "cuffs", "patch_pockets",
                    "chest_pocket", "topstitching", "yoke", "spaghetti_straps", "straps",
                    "drawstring_hem", "tie_front", "smocking", "elastic_hem"],
        "closures": ["button_front", "center_front_zip", "none"],
        "has_waistband": False,
        "has_darts": True,
    },
    "blouse": {
        "silhouettes": ["fitted", "relaxed", "peasant", "wrap", "peplum"],
        "sleeve_lengths": ["short", "long", "three_quarter", "sleeveless"],
        "necklines": ["crew", "v_neck", "round", "polo", "mandarin", "boat", "square", "halter", "strapless"],
        "length_categories": ["cropped", "hip_length", "tunic"],
        "details": ["collar", "v_neck", "round_neck", "ruffles", "lining_visible", "topstitching",
                    "spaghetti_straps", "straps", "tie_front", "smocking", "elastic_hem"],
        "closures": ["button_front", "center_back_zip", "none"],
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
        "closures": ["center_front_zip", "button_front", "snap_front", "double_breasted", "none"],
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
        "closures": ["button_front", "double_breasted", "center_front_zip", "none"],
        "has_waistband": False,
        "has_darts": True,
    },
    "vest": {
        "silhouettes": ["slim", "fitted", "regular", "relaxed", "boxy", "oversized", "longline"],
        "necklines": [
            "notched_v", "split_v", "v_neck", "crew", "round", "scoop", "square", "boat",
            "mandarin",
        ],
        "length_categories": ["cropped", "hip_length", "longline"],
        "details": [
            "welt_pockets", "besom_pockets", "patch_pockets",
            "neckline_binding", "contrast_binding", "armhole_binding", "hem_binding",
            "armhole_facing", "hem_facing", "neckline_facing",
            "mandarin_collar", "asymmetric_wrap",
            "lining_visible", "topstitching",
        ],
        "closures": ["button_front", "center_front_zip", "none"],
        "has_waistband": False,
        "has_darts": True,
        "has_edge_finishes": True,
        "has_shape": True,
    },
    "bodice": {
        "silhouettes": ["fitted", "boned", "relaxed", "wrap"],
        "necklines": ["crew", "round", "scoop", "v_neck", "square", "sweetheart"],
        "length_categories": ["cropped", "waist_length", "hip_length"],
        "details": ["boning", "lining_visible", "topstitching", "busk", "lace_up", "zipper"],
        "closures": ["center_back_zip", "hook_and_eye", "center_front_zip", "none"],
        "has_waistband": False,
        "has_darts": True,
        "has_shape": True,
    },
    "coat": {
        "silhouettes": ["a_line", "straight", "fitted", "wrap", "trench"],
        "length_categories": ["hip_length", "knee", "midi", "maxi"],
        "details": ["collar", "lapels", "patch_pockets", "welt_pockets", "lining_visible",
                    "topstitching", "belt", "hood", "double_breasted"],
        "closures": ["button_front", "center_front_zip", "double_breasted", "none"],
        "has_waistband": False,
        "has_darts": True,
    },
    "shorts": {
        "silhouettes": ["straight", "fitted", "wide_leg", "bermuda", "bike"],
        "length_categories": ["micro", "short", "mid_thigh", "knee"],
        "details": ["belt_loops", "patch_pockets", "side_pockets", "cuffs",
                    "elastic_waist", "topstitching"],
        "closures": ["button_fly", "side_zip", "none"],
        "has_waistband": True,
        "has_darts": False,
    },
}

# Fallback for any type not explicitly listed
_DEFAULT_VOCAB = {
    "silhouettes": ["fitted", "relaxed", "straight", "flared", "wrap"],
    "length_categories": ["short", "mid", "long"],
    "details": ["pockets", "lining_visible", "topstitching"],
    "closures": ["center_back_zip", "side_zip", "button_front", "button_fly",
                 "hook_and_eye", "center_front_zip", "none"],
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
        if gtype in ("trousers", "pants", "shorts", "skirt", "dress",
                     "jacket", "blazer", "coat")
        else ""
    )

    # Pocket-shape detection applies to any garment whose vocab includes a flat
    # applied pocket. Expose the shape tokens to the model and explain them.
    details_vocab = list(vocab["details"])
    has_patch = any(d in details_vocab for d in ("patch_pockets", "chest_pocket"))
    if has_patch:
        details_vocab = details_vocab + _POCKET_SHAPE_TOKENS
    pocket_shape_note = f'\n{_POCKET_SHAPE_NOTE}\n' if has_patch else ""

    # Construction-topology object, offered for upper-body garments (those with a
    # neckline vocab: shirt / blouse / dress). Lets the model report halter straps,
    # backless backs, and plunging open fronts that the neckline alone can't capture.
    has_necklines = "necklines" in vocab
    construction_line = (
        'construction: an object describing how the garment is built, or null when it is a '
        'plain shoulder-seam garment — '
        '{ "strap_style": "shoulder_seam" | "halter_neck" | "halter_tie" | "spaghetti_straps" | '
        '"wide_straps" | "one_shoulder" | "strapless" | "racerback", '
        '"back_coverage": "full" | "low_back" | "backless" | "racer", '
        '"front_opening": "closed" | "plunge" | "deep_v_split" | "keyhole" | "surplice" | '
        '"placket" | "wrap", '
        '"strap_width": "thin" | "medium" | "wide" | null }\n'
        if has_necklines else ''
    )
    construction_note = f'\n{_CONSTRUCTION_NOTE}\n' if has_necklines else ''

    # Structured pleat field + taxonomy, offered for every garment type.
    pleat_line = (
        'pleats: an object describing pleats, or null when there are none — '
        '{ "type": "knife" | "box" | "inverted_box" | "accordion" | "pintuck" | "none", '
        '"count": number, '
        '"placement": "front_waist" | "back_waist" | "all_around" | '
        '"center_front" | "center_back" | "skirt" | "none", '
        '"depth_cm": number }\n'
    )

    # Closure vocabulary is garment-specific: a front-zip jacket needs
    # 'center_front_zip', which makes no sense for a skirt. Falling back to the
    # default keeps any unlisted type usable.
    # Edge-finish fields (binding / facings / welt_pockets) for garments that support
    # bound and faced edges (vests). Lets the model report the contrast neckline binding,
    # faced armholes/hem, and bound welt pockets the other fields cannot capture.
    has_edge_finishes = vocab.get("has_edge_finishes", False)
    edge_finish_line = (
        'binding: an object for continuous edge binding, or null — '
        '{ "edges": array of "neckline" | "armhole" | "hem", '
        '"width_cm": number, "contrast": true | false }\n'
        'facings: array of "armhole" | "hem" | "neckline" (edges finished with a turned '
        'facing); empty array when none\n'
        'welt_pockets: array of objects, or empty array — each '
        '{ "position": "lower_front" | "chest" | "side_front" | "back", '
        '"width_cm": number, "count": number, "besom": true | false }\n'
        if has_edge_finishes else ''
    )
    edge_finish_note = f'\n{_EDGE_FINISH_NOTE}\n' if has_edge_finishes else ''

    # Silhouette/contour object (hem style + taper) for shape-aware garments (vest / bodice).
    has_shape = vocab.get("has_shape", False)
    shape_line = (
        'shape: an object describing the garment contour, or null — '
        '{ "hem_style": "straight" | "pointed" | "angled" | "curved_scoop" | "high_low" | '
        '"cutaway", "hem_depth_cm": number, "waist_taper_cm": number, "hem_sweep_cm": number, '
        '"high_low_cm": number, "side_vent_cm": number, '
        '"front_cut": "closed" | "cutaway" | "open_drape", "front_cut_depth_cm": number }\n'
        if has_shape else ''
    )
    shape_note = f'\n{_SHAPE_NOTE}\n' if has_shape else ''

    # Asymmetric-front object (vest/bodice): a diagonal wrap where the two fronts are DIFFERENT
    # panels — the structured fields can only express symmetric fronts otherwise.
    asymmetry_line = (
        'asymmetry: an object describing an asymmetric front, or null — '
        '{ "front_style": "symmetric" | "asymmetric_wrap", '
        '"wrap_side": "left" | "right", "overlap_cm": number, "closure_drop_frac": number }\n'
        if has_shape else ''
    )
    asymmetry_note = (
        '\nAsymmetric front — set front_style="asymmetric_wrap" ONLY when one front panel crosses '
        'the body DIAGONALLY over the other and the two fronts are clearly DIFFERENT shapes (e.g. a '
        'Chinese/Tang wrap vest fastened off to one side). wrap_side = the shoulder the wrap is '
        'anchored high at; overlap_cm = how far it crosses past the centre; closure_drop_frac = where '
        'the diagonal lands (0 = underarm … 1 = hem). A normal symmetric or evenly-overlapped '
        'wrap/surplice front is "symmetric".\n'
        if has_shape else ''
    )

    closures = vocab.get("closures", _DEFAULT_VOCAB["closures"])
    closure_options = " | ".join(f'"{c}"' for c in closures)

    return (
        f'You are a garment analysis expert. Analyze the provided {gtype} photograph(s) '
        f'and return ONLY a JSON object with no additional text. Identify:\n\n'
        f'1. garment_type: "{gtype}"\n'
        f'2. silhouette: one of {vocab["silhouettes"]}\n'
        f'   length_category: one of {vocab["length_categories"]}\n'
        f'{waistband_line}'
        f'4. closure: {{"type": {closure_options},'
        f' "position": "center_back" | "left_side" | "right_side" | "center_front"}}\n'
        f'   Pick the closure type AND its matching position from what is actually visible '
        f'(e.g. a front zipper is "center_front_zip" at "center_front", not a back zip). '
        f'Use "none" only when there is no visible fastening at all.\n'
        f'{darts_line}'
        f'6. details: array of strings from {details_vocab}\n'
        f'{pocket_note}'
        f'{pocket_shape_note}'
        f'{sleeve_line}'
        f'{neckline_line}'
        f'{construction_line}'
        f'{construction_note}'
        f'{edge_finish_line}'
        f'{edge_finish_note}'
        f'{shape_line}'
        f'{shape_note}'
        f'{asymmetry_line}'
        f'{asymmetry_note}'
        f'{pleat_line}'
        f'{_PLEAT_NOTE}\n'
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
