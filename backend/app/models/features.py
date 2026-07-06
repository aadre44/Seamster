from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class GarmentType(str, Enum):
    SKIRT = "skirt"
    DRESS = "dress"
    TROUSERS = "trousers"
    PANTS = "pants"
    SHIRT = "shirt"
    BLOUSE = "blouse"
    JACKET = "jacket"
    BLAZER = "blazer"
    VEST = "vest"
    BODICE = "bodice"
    COAT = "coat"
    SHORTS = "shorts"
    # Composed garments — no dedicated block; built by patterns/compositions.py
    # from existing builders (tunic = longline shirt; romper/jumpsuit = shirt
    # top + trouser bottom joined at a waist seam).
    TUNIC = "tunic"
    ROMPER = "romper"
    JUMPSUIT = "jumpsuit"


class WaistbandFeature(BaseModel):
    type: Literal["straight", "contoured", "elastic", "facing", "yoke"]
    width_cm_estimate: float = 3.0


class ClosureFeature(BaseModel):
    type: Literal[
        # bottom / dress closures
        "center_back_zip", "side_zip", "button_fly", "hook_and_eye",
        # front-opening closures (shirts, jackets, coats, blazers)
        "center_front_zip", "button_front", "snap_front", "double_breasted",
        "none",
    ]
    position: Literal["center_back", "left_side", "right_side", "center_front"]


class DartFeature(BaseModel):
    front: int = Field(ge=0, le=4)
    back: int = Field(ge=0, le=4)


class PleatDetail(BaseModel):
    """Structured pleat description so the engine can add real fabric allowance
    and fold/placement markings sized to what was actually observed.

    type       : knife (all folds same direction) | box (folds face away) |
                 inverted_box (folds face toward the centre seam) |
                 accordion (even zig-zag) | pintuck (tiny stitched tucks) | none
    count      : number of pleats visible across the garment (per the photo)
    placement  : where the pleats sit on the garment
    depth_cm   : finished depth of each pleat in cm; 0 => engine auto-sizes
    """
    type: Literal["knife", "box", "inverted_box", "accordion", "pintuck", "none"] = "none"
    count: int = Field(default=0, ge=0, le=40)
    placement: Literal[
        "front_waist", "back_waist", "all_around",
        "center_front", "center_back", "skirt", "none",
    ] = "none"
    depth_cm: float = Field(default=0.0, ge=0, le=20)


class Construction(BaseModel):
    """Orthogonal construction-topology axes that the neckline/details model cannot
    express on its own. Applies to upper-body garments (shirt, blouse, dress, bodice).

    These three axes recur independently across many designs — a garment can mix any
    combination (e.g. a halter strap with a backless back and a plunging open front).

    strap_style    : how the garment is held up at the top.
        shoulder_seam   — normal shoulder seam (default; current behaviour)
        halter_neck     — integral strap rises from the front and loops behind the
                          neck; there is NO shoulder seam and (usually) no back panel
        halter_tie      — same construction, finished as ties at the back neck
        spaghetti_straps— thin separate straps
        wide_straps     — wide separate straps
        one_shoulder    — a single asymmetric shoulder strap
        strapless       — no straps at all (band top)
        racerback       — straps converge to a narrow racer at the back

    back_coverage  : how much of the back the garment covers.
        full      — full back panel (default)
        low_back  — back drops to a low scoop / drape
        backless  — open back; no back bodice
        racer     — narrow racer-shaped back

    front_opening  : the centre-front treatment.
        closed       — closed CF (default; cut on fold)
        plunge       — deep V / U opening toward the waist
        deep_v_split — open all the way to the hem (two front halves)
        keyhole      — small CF cut-out
        surplice     — crossed-over wrap front
        placket      — buttoned CF placket
        wrap         — wrap-over CF

    strap_width    : how wide the strap reads in the photo (None ⇒ the generator uses a
                     sensible per-style default). Drives the integral halter strap and the
                     separate spaghetti/wide strap pieces.
        thin   — skinny / spaghetti (~1–2 cm)
        medium — a moderate strap (~3–4 cm)
        wide   — a thick band the bust flares into (~5–8 cm)
    """
    strap_style: Literal[
        "shoulder_seam", "halter_neck", "halter_tie",
        "spaghetti_straps", "wide_straps", "one_shoulder", "strapless", "racerback",
    ] = "shoulder_seam"
    back_coverage: Literal["full", "low_back", "backless", "racer"] = "full"
    front_opening: Literal[
        "closed", "plunge", "deep_v_split", "keyhole", "surplice", "placket", "wrap",
    ] = "closed"
    strap_width: Literal["thin", "medium", "wide"] | None = None


class BindingFeature(BaseModel):
    """Continuous narrow binding/piping that wraps one or more finished edges.

    Models the signature contrast trim on bound-edge garments (e.g. a vest neckline
    finished in a thin dark bias binding). Distinct from a facing: a binding wraps the
    raw edge and shows as a visible strip on the right side, optionally in a contrast
    fabric/colour, whereas a facing turns fully to the inside.

    edges    : which finished edges the binding runs along — any of
               "neckline", "armhole", "hem", "front_opening".
    width_cm : finished visible width of the binding on the right side (cm).
    contrast : True when the binding is a contrasting colour/fabric (drives the
               instruction + cutting layer to cut it from the contrast cloth).
    """
    edges: list[Literal["neckline", "armhole", "hem", "front_opening"]] = Field(default_factory=list)
    width_cm: float = Field(default=1.0, ge=0.2, le=8.0)
    contrast: bool = True


class WeltPocketFeature(BaseModel):
    """A placeable bound/welt (besom) pocket.

    position : where the pocket sits on the garment.
    width_cm : finished welt opening width (cm).
    count    : how many of these pockets appear (e.g. 2 for a symmetric pair).
    besom    : True for a double-besom (two narrow lips) rather than a single welt.
    """
    position: Literal[
        "lower_front", "chest", "side_front", "back",
    ] = "lower_front"
    width_cm: float = Field(default=14.0, ge=4.0, le=30.0)
    count: int = Field(default=1, ge=1, le=4)
    besom: bool = False


ShapeMode = Literal["modifiers", "warp", "fit_params"]
HemStyle = Literal["straight", "pointed", "angled", "curved_scoop", "high_low", "cutaway"]


class ShapeFeature(BaseModel):
    """The detected SILHOUETTE/contour of a garment, independent of its pieces and trim.

    One structured description that every shape-generation mode consumes, so the modes can
    be compared apples-to-apples (the difference is the strategy, not the input):

    hem_style      : contour of the bottom edge.
        straight     — flat horizontal hem (default)
        pointed      — drops to a centre-front apex below the side corners (a V hem)
        angled       — straight diagonal from CF down to the side (or vice-versa)
        curved_scoop — smooth curved hem (dips or rises at CF)
        high_low     — CF and side hems sit at different heights (see high_low_cm)
        cutaway      — the CF-hem corner is curved away (open/rounded front like a waistcoat)
    hem_depth_cm   : how far the apex / scoop deviates from the straight hemline (cm).
    waist_taper_cm : extra side-seam suppression at the waist (cm; + = more fitted).
    hem_sweep_cm   : side-seam offset at the hem (cm; + = flare/swing, − = taper/pegged).
    high_low_cm    : signed CF-minus-side hem height difference for high_low (cm).
    """
    hem_style: HemStyle = "straight"
    hem_depth_cm: float = Field(default=0.0, ge=0, le=30)
    waist_taper_cm: float = Field(default=0.0, ge=-10, le=20)
    hem_sweep_cm: float = Field(default=0.0, ge=-20, le=40)
    high_low_cm: float = Field(default=0.0, ge=-30, le=30)
    # side vent: leave the lower side seam open this many cm above the hem (0 = no vent).
    side_vent_cm: float = Field(default=0.0, ge=0, le=40)
    # front cut: how the two fronts meet below the closure.
    #   closed     — fronts meet/overlap normally (default; includes wrap/surplice overlaps)
    #   cutaway    — the lower centre-front curves away so the hem opens (waistcoat cutaway)
    #   open_drape — the centre-front is open from a high break to the hem (panels separate)
    front_cut: Literal["closed", "cutaway", "open_drape"] = "closed"
    front_cut_depth_cm: float = Field(default=0.0, ge=0, le=40)


class SilhouettePath(BaseModel):
    """Normalized control-point hull(s) for the WARP shape mode.

    front / back : ordered (x, y) points in 0–1 space over the panel's side+hem region
                   (x: 0 = CF/CB fold, 1 = side seam; y: 0 = underarm/waist anchor, 1 = hem).
                   The engine scales these to the panel's bounding box and warps the
                   side+hem subpath onto them. Optional — synthesized from ShapeFeature when
                   absent so the warp mode always has input.
    panels       : optional per-piece hulls keyed by piece name (e.g. "overlap_front"), so an
                   asymmetric garment can supply a distinct outline for each panel rather than
                   the shared front/back. The warp mode applies these to the matching pieces.
    """
    front: list[tuple[float, float]] = Field(default_factory=list)
    back: list[tuple[float, float]] = Field(default_factory=list)
    panels: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)


class AsymmetryFeature(BaseModel):
    """Asymmetric front construction — the left and right fronts are DIFFERENT panels.

    Mirror-symmetric fronts (the default everywhere else) cannot express a diagonal wrap /
    surplice overlap where one panel crosses the body over the other (e.g. a Chinese-style
    vest). ``asymmetric_wrap`` makes the builder emit two distinct, non-mirrored fronts — an
    Overlap (wrap) Front and an Underlap Front — joined by a diagonal closure edge.

    front_style       : "symmetric" (default) | "asymmetric_wrap".
    wrap_side         : which shoulder the overlap panel is anchored high at (wearer's
                        left/right); the diagonal closure runs from that side's neck down to
                        the opposite lower front.
    overlap_cm        : how far the overlap panel crosses PAST the centre front (cm).
    closure_drop_frac : where the diagonal lands on the opposite side, 0 = underarm … 1 = hem.
    """
    front_style: Literal["symmetric", "asymmetric_wrap"] = "symmetric"
    wrap_side: Literal["left", "right"] = "right"
    overlap_cm: float = Field(default=12.0, ge=0, le=40)
    closure_drop_frac: float = Field(default=1.0, ge=0.0, le=1.0)


class ContourPoint(BaseModel):
    """One outline vertex of a PieceContour, in the contour's normalized space.

    The optional control points make the edge ARRIVING at this vertex (from the
    previous vertex) a cubic bezier — the same convention as tier-2 custom
    geometry and CurveSegment: cp1 sits near the previous vertex, cp2 near this
    one. Give all four values or none; a partial set is treated as a plain point.
    """
    x: float
    y: float
    cp1x: float | None = None
    cp1y: float | None = None
    cp2x: float | None = None
    cp2y: float | None = None


class PieceContour(BaseModel):
    """Normalized 2D outline of a garment piece the vision model saw but could not
    describe with any vocabulary token (novel-piece tier 5). The backend
    patternizes it into a real piece (vision_contours.py)."""
    detail: str                              # snake_case token, e.g. "cascade_panel"
    name: str = ""                           # display name; defaults from detail
    points: list[ContourPoint] = Field(default_factory=list)  # outline, y down, any scale
    width_frac: float = 0.25                 # piece width as a fraction of `reference`
    reference: str = "chest_cm"              # measurement that scales the piece
    cut_qty: int = 1
    attachment_label: str | None = None      # garment edge it sews to (hem/neckline/…)
    attachment_edges: list[int] | None = None  # 0-based outline edges carrying the label
    confidence: float = 0.5


class GarmentFeatures(BaseModel):
    """Generic feature set returned by vision analysis for any garment type."""
    garment_type: GarmentType
    silhouette: str
    length_category: str
    closure: ClosureFeature
    waistband: WaistbandFeature | None = None
    darts: DartFeature | None = None
    details: list[str] = Field(default_factory=list)
    sleeve_length: str | None = None   # "short" | "long" | "three_quarter" | "sleeveless"
    neckline: str | None = None         # "crew" | "v_neck" | "round" | "polo" | "boat" | "mandarin" | "notched_v" | "split_v"
    pleats: PleatDetail | None = None   # structured pleat description (type/count/placement/depth)
    construction: Construction | None = None  # strap_style / back_coverage / front_opening
    binding: BindingFeature | None = None     # continuous contrast edge binding (neckline/armhole/hem)
    facings: list[Literal["armhole", "hem", "neckline"]] = Field(default_factory=list)  # edges finished with a turned facing piece
    welt_pockets: list[WeltPocketFeature] = Field(default_factory=list)  # placeable bound/welt pockets
    shape: ShapeFeature | None = None         # silhouette/contour (hem style + taper/flare)
    silhouette_path: SilhouettePath | None = None  # normalized control-point hull (warp shape mode)
    asymmetry: AsymmetryFeature | None = None      # asymmetric wrap front (distinct overlap/underlap panels)
    piece_contours: list[PieceContour] = Field(default_factory=list)  # unnameable pieces as outlines
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


# Kept for backward compatibility with existing tests and the skirt pattern engine
class SkirtFeatures(BaseModel):
    garment_type: GarmentType = GarmentType.SKIRT
    silhouette: Literal["straight", "a_line", "pencil", "circle", "gathered", "pleated", "wrap"]
    length_category: Literal["mini", "above_knee", "knee", "midi", "maxi"]
    waistband: WaistbandFeature
    closure: ClosureFeature
    darts: DartFeature
    details: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str = ""
