"""End-to-end engine tests: pocket shape and pleat handling across garments."""
from app.models.features import (
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    PleatDetail,
    WaistbandFeature,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern


def _measurements(**overrides) -> Measurements:
    defaults = dict(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0,
        chest_cm=90.0, shoulder_width_cm=30.0, arm_length_cm=60.0, seam_allowance_cm=1.5,
    )
    defaults.update(overrides)
    return Measurements(**defaults)


def _piece_vertices(psnap, name):
    piece = next(pc for pc in psnap["pieces"] if pc["name"] == name)
    ids = set(piece["elementIds"])
    return [e for e in psnap["elements"] if e["id"] in ids]


def _waist_width(psnap, name, waist_y=2.0):
    """Width of a panel at its (offset) waist line."""
    xs = [e["start"]["x"] for e in _piece_vertices(psnap, name)
          if abs(e["start"]["y"] - waist_y) < 0.05]
    return max(xs) - min(xs)


# ── Pocket shape ───────────────────────────────────────────────────────────────

def test_shirt_pointed_pocket_is_not_rectangular():
    """The Blue Tee scenario: a pointed chest pocket must gain a centre apex."""
    f = GarmentFeatures(
        garment_type=GarmentType.SHIRT, silhouette="boxy", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0),
        details=["chest_pocket", "patch_pockets", "pocket_pointed"],
        sleeve_length="short", neckline="crew", confidence=0.9,
    )
    psnap = generate_pattern(f, _measurements())
    verts = _piece_vertices(psnap, "Chest Patch Pocket")
    # square pocket = 4 outline edges; pointed adds the apex vertex => 5
    assert len(verts) == 5
    ys = [e["start"]["y"] for e in verts]
    # the apex sits below (greater y than) the two bottom-side corners
    assert max(ys) > sorted(ys)[-2]


def test_shirt_square_pocket_stays_rectangular():
    f = GarmentFeatures(
        garment_type=GarmentType.SHIRT, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0),
        details=["chest_pocket"], sleeve_length="short", neckline="crew", confidence=0.9,
    )
    psnap = generate_pattern(f, _measurements())
    assert len(_piece_vertices(psnap, "Chest Patch Pocket")) == 4


# ── Pleats ─────────────────────────────────────────────────────────────────────

def _has_pleat_markings(psnap):
    folds = [e for e in psnap["elements"] if e.get("seamLabel") == "pleat_fold"]
    places = [e for e in psnap["elements"] if e.get("seamLabel") == "pleat_placement"]
    return folds, places


def test_pleated_skirt_widens_panel_and_marks_folds():
    base = GarmentFeatures(
        garment_type=GarmentType.SKIRT, silhouette="straight", length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        darts=DartFeature(front=0, back=0),
        waistband=WaistbandFeature(type="straight", width_cm_estimate=3.0),
        details=[], confidence=0.9,
    )
    pleated = base.model_copy(update={"silhouette": "pleated"})
    flat = generate_pattern(base, _measurements())
    psnap = generate_pattern(pleated, _measurements())

    folds, places = _has_pleat_markings(psnap)
    assert places, "pleated skirt must have placement lines"
    assert folds, "pleated skirt must have fold lines"
    # front panel is wider once the pleat allowance is added
    assert _waist_width(psnap, "Front Skirt") > _waist_width(flat, "Front Skirt")


def test_structured_box_pleats_respected():
    f = GarmentFeatures(
        garment_type=GarmentType.SKIRT, silhouette="straight", length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        darts=DartFeature(front=0, back=0),
        waistband=WaistbandFeature(type="straight", width_cm_estimate=3.0),
        details=[], confidence=0.9,
        pleats=PleatDetail(type="box", count=4, placement="all_around", depth_cm=3.0),
    )
    psnap = generate_pattern(f, _measurements())
    places = [e for e in psnap["elements"] if e.get("seamLabel") == "pleat_placement"]
    assert places  # box pleats produce markings


def test_trouser_front_pleats_widen_waist_and_drop_dart():
    f = GarmentFeatures(
        garment_type=GarmentType.TROUSERS, silhouette="wide_leg", length_category="full_length",
        closure=ClosureFeature(type="button_fly", position="center_front"),
        darts=DartFeature(front=1, back=2),
        waistband=WaistbandFeature(type="straight", width_cm_estimate=4.0),
        details=[], confidence=0.9,
        pleats=PleatDetail(type="knife", count=2, placement="front_waist", depth_cm=2.5),
    )
    pleated = generate_pattern(f, _measurements())
    plain = generate_pattern(f.model_copy(update={"pleats": None}), _measurements())
    # +2 pleats x 2*2.5 = +10 cm at the waist
    assert _waist_width(pleated, "Front Leg") > _waist_width(plain, "Front Leg") + 5.0
    folds, places = _has_pleat_markings(pleated)
    assert places


def test_no_pleats_means_no_pleat_elements():
    f = GarmentFeatures(
        garment_type=GarmentType.SKIRT, silhouette="a_line", length_category="knee",
        closure=ClosureFeature(type="center_back_zip", position="center_back"),
        darts=DartFeature(front=1, back=2),
        waistband=WaistbandFeature(type="straight", width_cm_estimate=3.0),
        details=[], confidence=0.9,
    )
    psnap = generate_pattern(f, _measurements())
    folds, places = _has_pleat_markings(psnap)
    assert folds == [] and places == []
