"""Shirt / blouse base block (Aldrich parametric method).

Coordinate system (matches frontend SVG canvas):
  - X increases rightward
  - Y increases downward
  - Origin: x=0 is CB/CF fold edge; y=0 is shoulder/nape level
  - y increases toward hem

Pieces produced depend on analyzed features:
  - Back Bodice and Front Bodice are always produced.
  - Sleeve is produced unless sleeve_length == "sleeveless".
  - Collar is produced when has_collar=True.
  - Cuffs are produced when has_cuffs=True and sleeve has a wrist opening.
  - When has_placket=True the front is cut off-fold with a 3 cm CF overlap.

Fit styles affect bodice geometry:
  - slim / fitted: tapered side seams, tighter armhole, no drop shoulder
  - regular / relaxed: moderate shaping, standard construction
  - boxy: straight sides, extended drop shoulder, deeper armhole
  - oversized: extreme drop shoulder, maximum ease, straight sides
  - athletic: tight waist, wide shoulders, no drop shoulder
  - longline: standard shaping, extended body length

Necklines supported:
  crew, round, scoop, v_neck, square, polo, boat, mandarin,
  turtleneck, mock_turtleneck, henley, off_shoulder, keyhole

Sleeve types supported:
  sleeveless, cap, short, flutter, three_quarter, bell,
  puff_short, long, puff_long
"""
from __future__ import annotations

from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.finishings import path_length
from app.patterns.skirts import MarkSpec, PieceSpec

EASE_CHEST = 6.0      # standard chest/bust ease added to the full chest circumference
EASE_HIP = 4.0        # hip ease for shirts long enough to cover the hips
_PLACKET_WIDTH = 3.0  # cm of CF overlap strip added when has_placket=True
_COLLAR_HEIGHT = 4.0  # cm stand-collar height
_CUFF_HEIGHT = 6.0    # cm cuff height
_RIB_COLLAR_H = 5.0   # cm flat height of rib collar band (folds to ~2.5 cm finished)

_STRAP_WIDTH = 3.0    # cm finished width of an integral halter strap (legacy default)
_HEM_CASING_H = 6.0   # cm flat height of an elastic/drawstring hem casing band

# Detected strap_width category → finished strap width in cm. Drives the integral halter
# strap and the separate spaghetti/wide strap pieces so the piece matches the photo.
_STRAP_CM = {"thin": 2.0, "medium": 4.0, "wide": 7.0}


def _strap_cm(strap_width: str | None, default: float) -> float:
    """Map a detected strap_width category to cm; fall back to a per-style default."""
    return _STRAP_CM.get(strap_width or "", default)

# strap_style values that build an integral halter front (strap is part of the piece,
# rises from the bodice and loops/ties behind the neck — no shoulder seam, no back).
_HALTER_STRAPS = {"halter_neck", "halter_tie"}
# Any strap_style other than a plain shoulder seam: these have NO shoulder seam, are
# always sleeveless, and get a shoulderless bodice (+ separate straps when not a halter).
_SHOULDERLESS_STRAPS = {
    "halter_neck", "halter_tie",
    "spaghetti_straps", "wide_straps", "one_shoulder", "strapless", "racerback",
}
# front_opening values that open the centre front (deep neckline).
_OPEN_FRONTS = {"plunge", "deep_v_split"}


def _rect_piece(
    name: str, width: float, height: float, cut_qty: int, sa: float,
    *, on_fold: bool = False, notes: str = "",
) -> PieceSpec:
    """A plain rectangular pattern piece (strap, tie, facing, casing band)."""
    return PieceSpec(
        name=name,
        outline=[
            Point(0.0, 0.0), Point(width, 0.0),
            Point(width, height), Point(0.0, height),
        ],
        darts=[],
        grain_start=Point(width * 0.5, height * 0.1),
        grain_end=Point(width * 0.5, height * 0.9),
        cut_qty=cut_qty,
        on_fold=on_fold,
        seam_allowance=sa,
        notes=notes,
    )

# Bezier "magic number" for approximating a quarter-circle arc
_KAPPA = 0.5523

# Necklines that use a curved (convex) opening rather than a pointed/straight edge
_CURVED_NECKLINES = {"crew", "round", "scoop", "keyhole"}


# Per-silhouette geometry parameters.
# shoulder_slope : cm drop from neckline level to shoulder tip
# armhole_extra  : cm added to the base arm_depth (chest/4 + 4)
# waist_suppress : how much narrower the side seam is at waist vs chest quarter
# drop_shoulder  : cm the shoulder tip extends beyond chest_qt toward the arm
_FIT_PARAMS: dict[str, dict] = {
    "slim":      dict(shoulder_slope=0.5,  armhole_extra=-1.0, waist_suppress=3.0, drop_shoulder=0.0),
    "fitted":    dict(shoulder_slope=0.5,  armhole_extra=-0.5, waist_suppress=2.0, drop_shoulder=0.0),
    "regular":   dict(shoulder_slope=1.5,  armhole_extra= 0.0, waist_suppress=1.0, drop_shoulder=0.0),
    "relaxed":   dict(shoulder_slope=2.0,  armhole_extra= 1.0, waist_suppress=0.0, drop_shoulder=0.0),
    "boxy":      dict(shoulder_slope=2.5,  armhole_extra= 2.0, waist_suppress=0.0, drop_shoulder=1.5),
    "oversized": dict(shoulder_slope=3.5,  armhole_extra= 3.0, waist_suppress=0.0, drop_shoulder=3.0),
    "athletic":  dict(shoulder_slope=1.0,  armhole_extra=-0.5, waist_suppress=3.0, drop_shoulder=0.0),
    "longline":  dict(shoulder_slope=1.5,  armhole_extra= 0.0, waist_suppress=0.5, drop_shoulder=0.0),
}
_DEFAULT_FIT = _FIT_PARAMS["regular"]


def _labelled_length(spec: PieceSpec, label: str) -> float:
    """Total length of a piece's outline edges carrying `label` (curves followed)."""
    n = len(spec.outline)
    return sum(path_length([spec.outline[i], spec.outline[(i + 1) % n]])
               for i, lab in spec.edge_labels.items() if lab == label)


def build_shirt_block(
    m: Measurements,
    chest_ease_extra: float = 0.0,
    fit_style: str = "regular",
    sleeve_length: str = "long",
    neckline: str = "crew",
    has_placket: bool = False,
    has_collar: bool = False,
    has_cuffs: bool = False,
    has_ribbed_collar: bool = False,
    has_elastic_hem: bool = False,
    strap_style: str = "shoulder_seam",
    back_coverage: str = "full",
    front_opening: str = "closed",
    strap_width: str | None = None,
) -> dict[str, PieceSpec]:
    """Return shirt pattern pieces shaped by the analyzed garment features.

    chest_ease_extra : adjusts EASE_CHEST for different silhouettes.
    fit_style        : controls bodice shape (slope, suppression, drop shoulder).
    sleeve_length    : sleeveless | cap | short | flutter | three_quarter | bell |
                       puff_short | long | puff_long
    neckline         : crew | round | scoop | v_neck | square | polo | boat |
                       mandarin | turtleneck | mock_turtleneck | henley |
                       off_shoulder | keyhole
    has_placket      : front piece is off-fold with a 3 cm CF overlap strip
    has_collar       : add a rectangular stand collar piece
    has_cuffs        : add rectangular cuff pieces (only when wrist opening exists)
    has_elastic_hem  : add an elastic/drawstring Hem Casing Band piece
    strap_style      : shoulder_seam (default) | halter_neck | halter_tie | spaghetti_straps |
                       wide_straps | one_shoulder | strapless | racerback. Any non-shoulder
                       value is sleeveless + shoulderless: a halter builds one continuous
                       "Front" with an integral neck strap; the others build a strapless-style
                       "Front" plus separate strap pieces. All add a Front Facing.
    back_coverage    : full (default) | low_back | racer | backless — backless omits the
                       Back Bodice and adds a Waist Tie; a shoulderless top gets a flat-top
                       half-back band.
    front_opening    : closed (default) | plunge | deep_v_split | … — plunge drops the
                       centre-front into a deep V but keeps ONE piece on the fold; only
                       deep_v_split divides the front (a halter stays one piece joined by the
                       strap; a shoulder-seam front is cut off-fold as two halves).
    strap_width      : thin | medium | wide | None — finished strap width (≈2/4/7 cm). Sizes
                       the integral halter strap and the separate spaghetti/wide strap pieces;
                       None falls back to a per-style default.
    """
    # ── Resolve optional measurements ────────────────────────────────────────
    chest = m.chest_cm if m.chest_cm is not None else (m.hip_cm - 4.0)
    shoulder = m.shoulder_width_cm if m.shoulder_width_cm is not None else (chest / 4 + 7.5)
    arm_length = m.arm_length_cm if m.arm_length_cm is not None else 60.0
    W = m.waist_cm
    L = m.length_cm

    # ── Construction topology ─────────────────────────────────────────────────
    strap_style   = (strap_style or "shoulder_seam").lower()
    back_coverage = (back_coverage or "full").lower()
    front_opening = (front_opening or "closed").lower()
    is_halter   = strap_style in _HALTER_STRAPS
    is_shoulderless = strap_style in _SHOULDERLESS_STRAPS
    is_open_front = front_opening in _OPEN_FRONTS
    # A deep_v_split opens to the hem; a plunge opens to roughly the waist.
    split_to_hem  = front_opening == "deep_v_split"

    # Any strapped / halter top is sleeveless and has no shoulder seam — never build a
    # sleeve for it regardless of the (possibly stale/defaulted) sleeve_length signal.
    if is_shoulderless:
        sleeve_length = "sleeveless"

    # ── Fit-style parameters ──────────────────────────────────────────────────
    fit_style = (fit_style or "regular").lower()
    fp = _FIT_PARAMS.get(fit_style, _DEFAULT_FIT)
    shoulder_slope = fp["shoulder_slope"]
    armhole_extra  = fp["armhole_extra"]
    waist_suppress = fp["waist_suppress"]
    drop_shoulder  = fp["drop_shoulder"]

    # ── Quarter / key measurements ────────────────────────────────────────────
    total_ease = EASE_CHEST + chest_ease_extra
    chest_qt = (chest + total_ease) / 4

    shoulder_qt = shoulder / 2
    back_neck_w = chest / 10 + 1.0
    front_neck_w = back_neck_w

    arm_depth = chest / 4 + 4.0 + armhole_extra
    waist_y = arm_depth + 18.0

    # Side-seam width at waist level (narrower for fitted styles)
    waist_side_b = chest_qt - waist_suppress
    waist_side_f = chest_qt - waist_suppress

    # Hem quarter for a shaped side seam. At or above the waist it is the waist
    # quarter; a longer shirt must clear the hips, so below the waist the hem
    # widens toward the hip quarter (+ ease), reaching it at hip level. (Drawing
    # a hip-length hem at waist width made it ~20 cm too small for the hips.)
    hip_qt = (m.hip_cm + EASE_HIP) / 4

    def _hem_qt(waist_qt: float) -> float:
        if L <= waist_y:
            return waist_qt
        f = min(1.0, (L - waist_y) / max(m.waist_to_hip_cm, 1.0))
        return max(waist_qt, waist_qt + (hip_qt - waist_qt) * f)

    hem_qt_b = _hem_qt(W / 4)
    hem_qt_f = _hem_qt(W / 4 + 1.0)

    cap_height = chest / 8
    cap_w_half = chest_qt - 1.0

    # ── Neckline depth and shape ──────────────────────────────────────────────
    neckline = (neckline or "crew").lower()

    if neckline == "crew":
        front_neck_depth = chest / 10 + 2.0
    elif neckline == "round":
        front_neck_depth = chest / 10 + 3.5
        front_neck_w = back_neck_w * 1.1
    elif neckline == "scoop":
        front_neck_depth = chest / 10 + 5.5
        front_neck_w = back_neck_w * 1.3
    elif neckline == "v_neck":
        front_neck_depth = chest / 10 + 12.0
    elif neckline == "square":
        front_neck_depth = chest / 10 + 3.5
        front_neck_w = back_neck_w * 1.2
    elif neckline == "polo":
        front_neck_depth = chest / 10 + 1.0
    elif neckline == "boat":
        front_neck_depth = chest / 10 + 1.5
        front_neck_w = chest / 7
    elif neckline == "mandarin":
        front_neck_depth = chest / 10 + 1.0
    elif neckline in ("turtleneck", "mock_turtleneck"):
        front_neck_depth = chest / 10 + 0.5
    elif neckline == "henley":
        front_neck_depth = chest / 10 + 2.0
    elif neckline == "off_shoulder":
        front_neck_depth = shoulder_slope + 2.0
        front_neck_w = shoulder_qt
    elif neckline == "keyhole":
        front_neck_depth = chest / 10 + 2.5
    else:
        front_neck_depth = chest / 10 + 2.0

    # ── Shoulder tip x position (drop shoulder shifts it outward) ─────────────
    shoulder_tip_x = shoulder_qt + drop_shoulder

    # ── Armhole curve (shoulder tip → armscye): used on both bodices ──────────
    # CurveSegment means the edge arriving AT this vertex is a bezier.
    # cp1 is near the shoulder (going mostly downward/inward), cp2 is near the
    # armscye (arriving from slightly outside the side seam).
    _armhole_pt: Point | CurveSegment = CurveSegment(
        x=chest_qt, y=arm_depth,
        cp1=Point(shoulder_tip_x - 0.4, shoulder_slope + (arm_depth - shoulder_slope) * 0.45),
        cp2=Point(chest_qt + 1.5, arm_depth - (arm_depth - shoulder_slope) * 0.12),
    )

    # ── Back panel (gated by back_coverage; shape depends on strap_style) ──────
    # backless → no back panel at all (held up by halter straps / a waist tie).
    # Shoulderless garments get a band-style back (straight top edge, NO shoulder seam).
    #   Its height depends on the strap style so it MATCHES the front side seam:
    #     - halter → low band at the underarm (bare upper back, a "half back").
    #     - spaghetti/wide/one_shoulder/racerback (a tank/cami) → higher band at the
    #       upper back so the straps reach over the shoulders and the shoulder blades are
    #       covered (this is what makes a tank read as a tank, not a bandeau).
    #     - strapless → a tube/bandeau band at the same upper level as its front.
    # Shoulder-seam garments keep a conventional back; low_back scoops the CB neck
    #   and racer narrows the back neck + shoulder.
    band_top_y = arm_depth * 0.35           # upper-bust/back band level (shared with the front)
    back_spec: PieceSpec | None = None
    if back_coverage != "backless" and is_shoulderless:
        # Match the back top edge to the front side-seam top: halter fronts meet the side
        # seam at the underarm (arm_depth); band fronts (strapless/tank) meet it higher.
        top_y = arm_depth if is_halter else band_top_y
        _band_top = [Point(0.0, top_y), Point(chest_qt, top_y)]
        if waist_suppress == 0.0:
            back_outline = _band_top + [Point(chest_qt, L), Point(0.0, L)]
        else:
            back_outline = _band_top + [
                Point(waist_side_b, waist_y), Point(hem_qt_b, L), Point(0.0, L),
            ]
        _bn = len(back_outline)
        back_spec = PieceSpec(
            name="Back Bodice",
            outline=back_outline,
            darts=[],
            grain_start=Point(chest_qt / 2, (top_y + L) / 2),
            grain_end=Point(chest_qt / 2, L * 0.9),
            cut_qty=2,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes=(
                "shoulderless back cut on fold at CB; straight top edge, no shoulder seam; "
                "finish the top edge; sew to the Front at the side seams; "
                + ("the halter strap ties behind the neck above it"
                   if is_halter else
                   "the straps attach at the top corners and pass over the shoulders to the Front")
            ),
            edge_labels={0: "neckline", **{i: "side_seam" for i in range(1, _bn - 2)}, _bn - 2: "hem", _bn - 1: "center_back"},
        )
    elif back_coverage != "backless":
        # Conventional shoulder-seam back. low_back scoops the CB neck; racer narrows it.
        back_neck_w_eff   = back_neck_w
        back_shoulder_tip = shoulder_tip_x
        cb_top_y          = 0.0                       # y of the CB top corner
        if back_coverage == "low_back":
            cb_top_y = arm_depth * 0.65               # scoop the centre-back down
        elif back_coverage == "racer":
            back_neck_w_eff   = back_neck_w * 0.45
            back_shoulder_tip = shoulder_qt * 0.6

        _back_armhole_pt: Point | CurveSegment = CurveSegment(
            x=chest_qt, y=arm_depth,
            cp1=Point(back_shoulder_tip - 0.4, shoulder_slope + (arm_depth - shoulder_slope) * 0.45),
            cp2=Point(chest_qt + 1.5, arm_depth - (arm_depth - shoulder_slope) * 0.12),
        )

        _back_top = [
            Point(0.0, cb_top_y),
            Point(back_neck_w_eff, cb_top_y),
            Point(back_shoulder_tip, shoulder_slope),
            _back_armhole_pt,
        ]
        if waist_suppress == 0.0:
            back_outline = _back_top + [Point(chest_qt, L), Point(0.0, L)]
        else:
            back_outline = _back_top + [
                Point(waist_side_b, waist_y), Point(hem_qt_b, L), Point(0.0, L),
            ]

        back_grain_x = chest_qt / 2
        _bn = len(back_outline)
        _back_note = {
            "full":     "main back panel cut on fold at CB; sew to Front Bodice at shoulder seams then side seams",
            "low_back": "low-back panel cut on fold at CB; centre-back is scooped low; finish the back neckline edge; sew to Front at shoulders and sides",
            "racer":    "racer back panel cut on fold at CB; narrow shoulders; finish the back neck/armhole edges; sew to Front at shoulders and sides",
        }[back_coverage]
        back_spec = PieceSpec(
            name="Back Bodice",
            outline=back_outline,
            darts=[],
            grain_start=Point(back_grain_x, arm_depth),
            grain_end=Point(back_grain_x, L * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes=_back_note,
            edge_labels={0: "neckline", 1: "shoulder", 2: "armhole", **{i: "side_seam" for i in range(3, _bn - 2)}, _bn - 2: "hem", _bn - 1: "center_back"},
        )

    # ── Front Bodice ──────────────────────────────────────────────────────────
    # Halter front: the neckline rises into an integral strap that ties behind the
    # neck (no shoulder seam). A plunge/closed front stays ONE piece cut on the CF
    # fold (the V is a notch, it does NOT divide the front); only a deep_v_split
    # opens the centre front all the way down into two mirrored halves.
    if is_halter:
        # Strap width comes from the detected strap_width (thin/medium/wide); default medium.
        halter_w     = _strap_cm(strap_width, default=4.0)     # finished strap width at the neck
        strap_base_x = max(front_neck_w, halter_w + 1.0)       # strap attaches near the neck
        strap_len    = max(25.0, arm_length * 0.5)             # length that ties behind the neck
        y0           = strap_len                               # bodice top sits below the strap
        # CF neck depth (bodice coords). Split → all the way to the hem; plunge →
        # deep toward the waist but kept above the hem so a CF fold remains.
        plunge_depth = L if split_to_hem else min(waist_y, L * 0.8)

        if not split_to_hem:
            # ONE-PIECE halter front, cut on the CF fold (no centre-front seam). The strap's
            # OUTER edge is a single smooth curve from the strap top down to the armscye, so
            # the bust flares gradually into the strap (no corner). Width = halter_w at the neck.
            _outer_flare = CurveSegment(
                x=chest_qt, y=y0 + arm_depth,                   # arrives at the armscye
                cp1=Point(strap_base_x + 1.0, y0 * 0.5),        # leaves the strap top ~strap-width
                cp2=Point(chest_qt + 1.5, y0 + arm_depth * 0.5),
            )
            front_outline: list[Point | CurveSegment] = [
                Point(0.0, y0 + plunge_depth),                 # 0 V-bottom on CF (fold start)
                Point(strap_base_x - halter_w, y0),            # 1 strap inner base (neckline V)
                Point(strap_base_x - halter_w, 0.0),           # 2 strap top, inner
                Point(strap_base_x, 0.0),                      # 3 strap top, outer
                _outer_flare,                                  # 4 gradual outer edge → armscye
            ]
            if waist_suppress == 0.0:
                front_outline += [Point(chest_qt, y0 + L), Point(0.0, y0 + L)]
            else:
                front_outline += [
                    Point(waist_side_f, y0 + waist_y),
                    Point(hem_qt_f, y0 + L),
                    Point(0.0, y0 + L),
                ]
            n = len(front_outline)
            # edges 0-2 = neckline (V + strap inner + strap top), 3 = the gradual strap→bust
            # curve (armhole), then side seam(s), hem (n-2), and the CF fold (n-1).
            _front_labels = {0: "neckline", 1: "neckline", 2: "neckline", 3: "armhole"}
            for i in range(4, n - 2):
                _front_labels[i] = "side_seam"
            _front_labels[n - 2] = "hem"
            _front_labels[n - 1] = "center_front"

            front_spec = PieceSpec(
                name="Front",
                outline=front_outline,
                darts=[],
                grain_start=Point(strap_base_x * 0.6, y0 + arm_depth * 0.5),
                grain_end=Point(strap_base_x * 0.6, y0 + L * 0.85),
                cut_qty=2,
                on_fold=True,
                seam_allowance=m.seam_allowance_cm,
                notes="continuous halter front cut ONE piece on the CF fold (the deep V is a notch, "
                      "not a seam); the integral straps tie behind the neck (no shoulder seam) and the "
                      "bust flares gradually into the strap; stay-stitch and face the neckline/strap "
                      "edges; join to the back at the side seams",
                edge_labels=_front_labels,
            )
        else:
            # DEEP V SPLIT: ONE continuous piece cut on the fold at the **back-neck**.
            # The fold is the TOP edge (the back-neck): one front panel + its strap is
            # drafted, and cutting on the fold mirrors it into the other panel + strap, so
            # the two panels are joined ONLY by the strap that runs over the neck. The
            # centre front is fully open (the two inner edges never meet below the strap).
            # x=0 is the CF/strap (inner) side; x grows toward the side seam. y=0 is the
            # back-neck fold; the strap drops to the bodice at y0, the hem is at y0+L.
            ih_hem = max(halter_w + 1.0, chest_qt * 0.25)       # inner (CF) edge x at the hem
            # Single smooth outer edge: armscye → strap top outer, so the bust flares
            # gradually into the strap (width = halter_w at the neck; no corner).
            _outer_flare = CurveSegment(
                x=halter_w, y=0.0,                              # arrives at the strap top outer
                cp1=Point(chest_qt, y0 + arm_depth * 0.35),     # leaves the armscye heading up
                cp2=Point(halter_w + 5.0, y0 * 0.55),           # approaches the strap top, flared below
            )
            front_outline = [
                Point(0.0, 0.0),           # 0 back-neck inner (fold start)
                Point(0.0, y0),            # 1 strap base inner
            ]
            _front_labels = {0: "neckline", 1: "neckline"}      # strap inner, then CF opening edge
            front_outline.append(Point(ih_hem, y0 + L))         # 2 inner hem (bottom of the CF opening)
            _front_labels[2] = "hem"
            if waist_suppress == 0.0:
                front_outline.append(Point(chest_qt, y0 + L))           # side hem
                _front_labels[len(front_outline) - 1] = "side_seam"
                front_outline.append(Point(chest_qt, y0 + arm_depth))   # armscye (underarm)
            else:
                front_outline.append(Point(hem_qt_f, y0 + L))        # side hem
                _front_labels[len(front_outline) - 1] = "side_seam"
                front_outline.append(Point(waist_side_f, y0 + waist_y)) # side at waist
                _front_labels[len(front_outline) - 1] = "side_seam"
                front_outline.append(Point(chest_qt, y0 + arm_depth))   # armscye (underarm)
            _front_labels[len(front_outline) - 1] = "armhole"           # armscye → strap top (gradual curve)
            front_outline.append(_outer_flare)                          # strap top outer (curve)
            _front_labels[len(front_outline) - 1] = "center_back"       # closing edge = TOP back-neck FOLD

            front_spec = PieceSpec(
                name="Front",
                outline=front_outline,
                darts=[],
                grain_start=Point(chest_qt * 0.5, y0 + arm_depth),
                grain_end=Point(chest_qt * 0.5, y0 + L * 0.9),
                cut_qty=2,
                on_fold=True,
                seam_allowance=m.seam_allowance_cm,
                notes="continuous halter front: cut ONE piece on the fold along the TOP (back-neck) "
                      "edge, so the strap mirrors over the neck and joins the two front panels — the "
                      "ONLY thing connecting them. The bust flares gradually into the strap; the centre "
                      "front is fully open (deep V split) below the strap. Cut 2 (one pair) if you prefer "
                      "a seam at the back-neck instead of a fold; face the neckline/strap edges; join to "
                      "the back at the sides",
                edge_labels=_front_labels,
            )
        _alt_front_spec = front_spec

    # ── Shoulderless (non-halter) Front: spaghetti / wide / one-shoulder / strapless ──
    # A strapless-style bodice cut ONE piece on the CF fold: a top edge that sits at the
    # upper bust (dipping into a deep V at the centre for a plunge), plus separate strap
    # pieces (none for strapless). The actual straps are cut separately and sewn on.
    extra_strap_pieces: dict[str, PieceSpec] = {}
    if is_shoulderless and not is_halter:
        # band_top_y (shared with the back) is the upper-bust band level.
        cf_top_y = min(waist_y, L * 0.8) if is_open_front else band_top_y

        sl_outline: list[Point | CurveSegment] = [
            Point(0.0, cf_top_y),            # 0 CF top (V dip for plunge, else band level)
            Point(chest_qt, band_top_y),     # 1 side top (under the arm)
        ]
        sl_labels: dict[int, str] = {0: "neckline"}
        sl_labels[len(sl_outline) - 1] = "side_seam"        # side top → next
        if waist_suppress == 0.0:
            sl_outline.append(Point(chest_qt, L))           # side hem
        else:
            sl_outline.append(Point(waist_side_f, waist_y)) # side at waist
            sl_labels[len(sl_outline) - 1] = "side_seam"
            sl_outline.append(Point(hem_qt_f, L))        # side hem
        sl_labels[len(sl_outline) - 1] = "hem"              # side hem → CF hem
        sl_outline.append(Point(0.0, L))                    # CF at hem
        sl_labels[len(sl_outline) - 1] = "center_front"     # closing edge = CF fold

        _alt_front_spec = PieceSpec(
            name="Front",
            outline=sl_outline,
            darts=[],
            grain_start=Point(chest_qt / 2, (cf_top_y + L) / 2),
            grain_end=Point(chest_qt / 2, L * 0.9),
            cut_qty=2,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes=(
                "shoulderless front cut ONE piece on the CF fold (no shoulder seam); the top edge sits "
                "at the upper bust" + ("; the centre front dips into a deep V" if is_open_front else "")
                + "; interface/face the top edge; the straps are cut separately and attached at the top edge"
            ),
            edge_labels=sl_labels,
        )

        # Separate strap pieces (thin/wide/single), cut as rectangles. The width follows the
        # detected strap_width when present, else the per-style default.
        _strap_len = max(30.0, arm_length * 0.5)
        _strap_specs = {  # (name, default width cm, cut qty)
            "spaghetti_straps": ("Strap", 2.0, 4),
            "wide_straps":      ("Wide Strap", 5.0, 4),
            "one_shoulder":     ("Shoulder Strap", 4.0, 2),
            "racerback":        ("Strap", 3.0, 4),
        }
        if strap_style in _strap_specs:
            _sname, _sdefault_w, _sqty = _strap_specs[strap_style]
            _swidth = _strap_cm(strap_width, default=_sdefault_w)
            extra_strap_pieces["strap"] = _rect_piece(
                _sname, _swidth, _strap_len, _sqty, m.seam_allowance_cm,
                notes=f"{_sname.lower()} (cut {_sqty}, ~{_swidth:.0f} cm wide); fold lengthwise RS "
                      "together, stitch and turn; attach to the bodice top edge at the front and over "
                      "the shoulder/back",
            )

    # ── Standard (non-halter, shoulder-seam) Front Bodice ──────────────────────
    # A non-halter open front drops the centre-front neck deep. A plunge stays ONE
    # piece on the fold (a deep V notch); only a deep_v_split is cut off-fold as two
    # halves (handled in the on-fold logic below).
    if is_open_front and not is_halter:
        front_neck_depth = max(front_neck_depth, L if split_to_hem else min(waist_y, L))

    # For curved necklines the shoulder-side neck point is reached via a bezier
    # curve from the CF depth point, giving a smooth crew/round/scoop opening.
    if neckline in _CURVED_NECKLINES:
        neck_shoulder_pt: Point | CurveSegment = CurveSegment(
            x=front_neck_w,
            y=0.0,
            cp1=Point(front_neck_w * _KAPPA, front_neck_depth),
            cp2=Point(front_neck_w, front_neck_depth * _KAPPA),
        )
    else:
        neck_shoulder_pt = Point(front_neck_w, 0.0)

    if neckline == "v_neck":
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(hem_qt_f, L),
                Point(0.0, L),
            ]
    elif neckline == "square":
        # Extra corner point creates the horizontal neckline edge
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                Point(front_neck_w, front_neck_depth),
                Point(front_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                Point(front_neck_w, front_neck_depth),
                Point(front_neck_w, 0.0),
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(hem_qt_f, L),
                Point(0.0, L),
            ]
    else:
        if waist_suppress == 0.0:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(chest_qt, L),
                Point(0.0, L),
            ]
        else:
            front_outline = [
                Point(0.0, front_neck_depth),
                neck_shoulder_pt,
                Point(shoulder_tip_x, shoulder_slope),
                _armhole_pt,
                Point(waist_side_f, waist_y),
                Point(hem_qt_f, L),
                Point(0.0, L),
            ]

    # Button placket: the extension lies BEYOND the CF line, so the front is
    # _PLACKET_WIDTH wider. The front edge stays at x = 0 and everything else
    # moves out (the CF line is now at x = _PLACKET_WIDTH). Moving the front edge
    # in instead made every button-front shirt 2 × 3 cm too small.
    if has_placket:
        def _widen(p: Point | CurveSegment) -> Point | CurveSegment:
            if isinstance(p, CurveSegment):
                return CurveSegment(p.x + _PLACKET_WIDTH, p.y,
                                    Point(p.cp1.x + _PLACKET_WIDTH, p.cp1.y), Point(p.cp2.x + _PLACKET_WIDTH, p.cp2.y))
            return p if p.x == 0.0 else Point(p.x + _PLACKET_WIDTH, p.y)
        front_outline = [_widen(p) for p in front_outline]
        front_on_fold = False
        front_cut_qty = 2
    elif split_to_hem and not is_halter:
        # deep_v_split only: CF opens to the hem → two halves, CF is a seamed/finished
        # edge, not a fold. A plunge stays ONE piece on the fold (just a deep V notch).
        front_on_fold = False
        front_cut_qty = 2
    else:
        front_on_fold = True
        front_cut_qty = 2

    front_grain_x = chest_qt / 2 + (_PLACKET_WIDTH if has_placket else 0.0)
    _front_fold_note = (
        "has button-placket extension at CF; cut 2 separate pieces; interface placket strip before folding"
        if has_placket else
        "cut on fold at CF"
    )
    _fn = len(front_outline)
    _n_neck = 2 if neckline == "square" else 1
    front_spec = PieceSpec(
        name="Front Bodice",
        outline=front_outline,
        darts=[],
        grain_start=Point(front_grain_x, arm_depth),
        grain_end=Point(front_grain_x, L * 0.85),
        cut_qty=front_cut_qty,
        on_fold=front_on_fold,
        seam_allowance=m.seam_allowance_cm,
        notes=f"main front panel; {_front_fold_note}; sew to Back Bodice at shoulder seams then side seams",
        edge_labels={**{i: "neckline" for i in range(_n_neck)}, _n_neck: "shoulder", _n_neck + 1: "armhole", **{i: "side_seam" for i in range(_n_neck + 2, _fn - 2)}, _fn - 2: "hem", _fn - 1: "center_front"},
    )

    # A button front: the centre-front line (where the buttons sit and where the
    # two fronts meet when buttoned) is marked _PLACKET_WIDTH in from the front edge.
    if has_placket:
        front_spec.marks.append(MarkSpec(points=[Point(_PLACKET_WIDTH, front_neck_depth), Point(_PLACKET_WIDTH, L)],
                                         label="center_front_line", dashed=True))

    # The halter / shoulderless branches built a one-piece "Front"; the standard branch
    # above recomputed a throwaway front_spec for those inputs — discard it here.
    if is_shoulderless:
        front_spec = _alt_front_spec
    pieces: dict[str, PieceSpec] = {("front" if is_shoulderless else "front_bodice"): front_spec}
    if back_spec is not None:
        pieces["back_bodice"] = back_spec
    pieces.update(extra_strap_pieces)

    # Neck opening, measured along the neckline edges (a scooped front neckline
    # is much longer than its width) and across the button extension: the
    # length a collar or neck band is sewn along.
    neck_half = _labelled_length(front_spec, "neckline") + (_labelled_length(back_spec, "neckline") if back_spec else 0.0)
    neck_circ = 2 * neck_half if neck_half > 0 else (back_neck_w + front_neck_w) * 2

    # ── Sleeve ────────────────────────────────────────────────────────────────
    sleeve_length = (sleeve_length or "long").lower()

    if sleeve_length == "sleeveless":
        pass
    else:
        # Determine sleeve length in cm and flare style
        flare_wrist: float | None = None  # None = standard taper; float = explicit wrist width

        if sleeve_length == "cap":
            actual_sleeve_len = 6.0
        elif sleeve_length == "short":
            actual_sleeve_len = 25.0
        elif sleeve_length == "flutter":
            actual_sleeve_len = 12.0
            flare_wrist = cap_w_half + 4.0
        elif sleeve_length == "three_quarter":
            actual_sleeve_len = arm_length * 0.67
        elif sleeve_length == "bell":
            actual_sleeve_len = arm_length
            flare_wrist = cap_w_half + 8.0
        elif sleeve_length == "puff_short":
            actual_sleeve_len = 18.0
            # Wider cap for gathering; taper back at hem
            cap_w_half = cap_w_half * 1.5
        elif sleeve_length == "puff_long":
            actual_sleeve_len = arm_length
            cap_w_half = cap_w_half * 1.5
        else:  # "long"
            actual_sleeve_len = arm_length

        total_sleeve_h = cap_height + actual_sleeve_len

        # Sleeve cap: curved dome from crown (0, 0) to underarm edge (cap_w_half, cap_height)
        _cap_curve = CurveSegment(
            x=cap_w_half, y=cap_height,
            cp1=Point(cap_w_half * 0.28, cap_height * 0.04),
            cp2=Point(cap_w_half * 0.88, cap_height * 0.45),
        )
        if flare_wrist is not None:
            sleeve_outline: list[Point | CurveSegment] = [
                Point(0.0, 0.0),
                _cap_curve,
                Point(flare_wrist, total_sleeve_h),
                Point(0.0, total_sleeve_h),
            ]
        else:
            sleeve_outline = [
                Point(0.0, 0.0),
                _cap_curve,
                Point(cap_w_half - 2.0, total_sleeve_h),
                Point(0.0, total_sleeve_h),
            ]

        _sleeve_notes: dict[str, str] = {
            "cap":        "cap sleeve; set directly into armscye with minimal ease; no sleeve seam",
            "short":      "short set-in sleeve; sew sleeve seam first to form tube, then ease cap into armscye",
            "flutter":    "flutter sleeve; no sleeve seam; attach wide hem edge directly to armscye; hem drapes freely",
            "three_quarter": "three-quarter set-in sleeve; sew sleeve seam to form tube, ease cap into armscye",
            "bell":       "bell-flared sleeve; sew sleeve seam to form tube, ease cap into armscye; flared hem requires no easing",
            "puff_short": "short puffed sleeve; gather wide cap before setting into armscye to create puff volume",
            "puff_long":  "long puffed sleeve; gather extra-wide cap before setting into armscye; gather hem before attaching cuff",
            "long":       "set-in sleeve; sew sleeve seam first to form tube, then ease cap into armscye",
        }
        sleeve_grain_x = cap_w_half / 2
        sleeve_spec = PieceSpec(
            name="Sleeve",
            outline=sleeve_outline,
            darts=[],
            grain_start=Point(sleeve_grain_x, cap_height * 0.5),
            grain_end=Point(sleeve_grain_x, total_sleeve_h * 0.85),
            cut_qty=2,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes=_sleeve_notes.get(sleeve_length, _sleeve_notes["long"]),
            edge_labels={0: "armhole", 1: "sleeve_seam", 2: "wrist", 3: "center_sleeve"},
        )
        pieces["sleeve"] = sleeve_spec

        # ── Cuffs (long / three_quarter only, not flared sleeves) ─────────────
        if has_cuffs and sleeve_length in ("long", "three_quarter"):
            wrist_w = (cap_w_half - 2.0) * 2
            cuff_outline = [
                Point(0.0, 0.0),
                Point(wrist_w, 0.0),
                Point(wrist_w, _CUFF_HEIGHT),
                Point(0.0, _CUFF_HEIGHT),
            ]
            cuff_spec = PieceSpec(
                name="Cuff",
                outline=cuff_outline,
                darts=[],
                grain_start=Point(wrist_w * 0.1, _CUFF_HEIGHT / 2),
                grain_end=Point(wrist_w * 0.9, _CUFF_HEIGHT / 2),
                cut_qty=2,
                on_fold=False,
                seam_allowance=m.seam_allowance_cm,
                notes="straight shirt cuff; interface both layers; sew short ends to form band; attach to sleeve hem RS together, fold under and topstitch",
                edge_labels={0: "wrist"},
            )
            pieces["cuff"] = cuff_spec

    # ── Collar ────────────────────────────────────────────────────────────────
    if has_collar:
        collar_w = neck_circ + m.seam_allowance_cm * 2
        collar_outline = [
            Point(0.0, 0.0),
            Point(collar_w, 0.0),
            Point(collar_w, _COLLAR_HEIGHT),
            Point(0.0, _COLLAR_HEIGHT),
        ]
        collar_spec = PieceSpec(
            name="Collar",
            outline=collar_outline,
            darts=[],
            grain_start=Point(collar_w * 0.1, _COLLAR_HEIGHT / 2),
            grain_end=Point(collar_w * 0.9, _COLLAR_HEIGHT / 2),
            cut_qty=2,
            on_fold=False,
            seam_allowance=m.seam_allowance_cm,
            notes="shirt collar band; interface both layers; sew outer collar to neckline RS together, then slip-stitch inner edge over seam allowance",
            edge_labels={0: "neckline"},
        )
        pieces["collar"] = collar_spec

    # ── Ribbed Collar Band ────────────────────────────────────────────────────
    # Only generated when the vision analysis explicitly detected one.
    # Cut slightly shorter than the neck opening so the rib stretches when sewn in.
    if has_ribbed_collar and not has_collar:
        rib_w = neck_circ * 0.9  # rib stretches ~10% when sewn to opening
        rib_outline = [
            Point(0.0, 0.0),
            Point(rib_w, 0.0),
            Point(rib_w, _RIB_COLLAR_H),
            Point(0.0, _RIB_COLLAR_H),
        ]
        rib_spec = PieceSpec(
            name="Ribbed Collar Band",
            outline=rib_outline,
            darts=[],
            grain_start=Point(rib_w * 0.1, _RIB_COLLAR_H / 2),
            grain_end=Point(rib_w * 0.9, _RIB_COLLAR_H / 2),
            cut_qty=1,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes="stretch rib collar band cut ~10% smaller than neckline opening; sew short ends to form loop; fold in half and attach RS together, stretching band to fit neckline",
        )
        pieces["rib_collar"] = rib_spec

    # ── Turtleneck / Mock Turtleneck Band ─────────────────────────────────────
    if neckline in ("turtleneck", "mock_turtleneck"):
        tube_h = 20.0 if neckline == "turtleneck" else 12.0
        band_w = neck_circ
        band_outline = [
            Point(0.0, 0.0),
            Point(band_w, 0.0),
            Point(band_w, tube_h),
            Point(0.0, tube_h),
        ]
        band_name = "Turtleneck Band" if neckline == "turtleneck" else "Mock Turtleneck Band"
        _band_note = (
            "full turtleneck band cut on fold; sew short ends to form tube; fold in half lengthwise and attach doubled edge to neckline RS together"
            if neckline == "turtleneck" else
            "mock turtleneck band cut on fold; sew short ends to form tube; fold in half and attach to neckline RS together; sits upright without folding over"
        )
        band_spec = PieceSpec(
            name=band_name,
            outline=band_outline,
            darts=[],
            grain_start=Point(band_w * 0.1, tube_h / 2),
            grain_end=Point(band_w * 0.9, tube_h / 2),
            cut_qty=1,
            on_fold=True,
            seam_allowance=m.seam_allowance_cm,
            notes=_band_note,
        )
        pieces["neck_band"] = band_spec

    # ── Henley Placket Strip ──────────────────────────────────────────────────
    if neckline == "henley":
        placket_h = front_neck_depth * 0.7
        placket_w = 4.0
        henley_outline = [
            Point(0.0, 0.0),
            Point(placket_w, 0.0),
            Point(placket_w, placket_h),
            Point(0.0, placket_h),
        ]
        henley_spec = PieceSpec(
            name="Henley Placket",
            outline=henley_outline,
            darts=[],
            grain_start=Point(placket_w * 0.1, placket_h / 2),
            grain_end=Point(placket_w * 0.9, placket_h / 2),
            cut_qty=1,
            on_fold=False,
            seam_allowance=m.seam_allowance_cm,
            notes="henley placket strip; finish long edges; slash front neckline and insert placket before assembling body; buttons/buttonholes along centre",
        )
        pieces["henley_placket"] = henley_spec

    sa = m.seam_allowance_cm

    # ── Front facing (halter / open plunging fronts) ──────────────────────────
    # Finishes the exposed neckline + plunge + strap edges from the inside.
    if is_halter or is_open_front or is_shoulderless:
        pieces["front_facing"] = _rect_piece(
            "Front Facing", max(8.0, chest_qt * 0.7), 7.0, 2, sa,
            notes="front neckline/plunge/top-edge facing (cut 2 mirrored); interface; sew to the "
                  "front neckline and centre-front opening RS together, understitch and turn inside",
        )

    # ── Waist tie (backless garments need something to hold them on) ──────────
    if back_coverage == "backless":
        pieces["waist_tie"] = _rect_piece(
            "Waist Tie", max(50.0, W * 0.75), 5.0, 2, sa,
            notes="waist tie (cut 2); fold lengthwise RS together, stitch and turn; attach at the "
                  "side seams so the backless top ties closed behind the waist",
        )

    # ── Elastic / drawstring hem casing band ──────────────────────────────────
    if has_elastic_hem:
        hem_circ = chest + total_ease
        pieces["hem_casing"] = _rect_piece(
            "Hem Casing Band", hem_circ, _HEM_CASING_H, 1, sa,
            notes="hem casing band; sew short ends to form a loop; attach to the garment hem RS "
                  "together, fold to the inside and topstitch to form a channel, then thread "
                  "elastic/drawstring through",
        )

    return pieces
