"""Tests for the bodice generator and the end-to-end shape_mode plumbing."""
from app.models.features import (
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    ShapeFeature,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern


def _m() -> Measurements:
    return Measurements(
        waist_cm=80.0, hip_cm=98.0, waist_to_hip_cm=21.0, length_cm=62.0,
        chest_cm=96.0, shoulder_width_cm=40.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


def _vest(shape: ShapeFeature | None) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="boxy", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0), neckline="notched_v", shape=shape, confidence=0.9,
    )


def _front_max_y(psnap: dict) -> float:
    fb = next(p for p in psnap["pieces"] if p["name"] == "Front Bodice")
    ys = [e["end"]["y"] for e in psnap["elements"] if e["pieceId"] == fb["id"] and "end" in e]
    return max(ys)


def test_bodice_is_no_longer_a_placeholder():
    feats = GarmentFeatures(
        garment_type=GarmentType.BODICE, silhouette="fitted", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"), neckline="v_neck",
        confidence=0.9,
    )
    psnap = generate_pattern(feats, _m())
    names = [p["name"] for p in psnap["pieces"]]
    assert "Front Bodice" in names and "Back Bodice" in names
    assert "notice" not in psnap


def test_all_three_modes_produce_valid_patterns():
    shape = ShapeFeature(hem_style="pointed", hem_depth_cm=5.0, hem_sweep_cm=6.0)
    for mode in ("modifiers", "warp", "fit_params"):
        psnap = generate_pattern(_vest(shape), _m(), mode)
        assert len(psnap["pieces"]) == 2
        labels = {c["label"] for c in psnap["connections"]}
        assert {"shoulder", "side_seam"} <= labels
        # Both panels keep their hem edge, but front and back hems are one
        # opening — they are never sewn to each other.
        assert "hem" not in labels
        for piece in psnap["pieces"]:
            ids = set(piece["elementIds"])
            assert any(e.get("seamLabel") == "hem" for e in psnap["elements"] if e["id"] in ids)


def test_pointed_modes_extend_hem_below_straight():
    straight = _front_max_y(generate_pattern(_vest(ShapeFeature()), _m(), "modifiers"))
    pointed_mod = _front_max_y(generate_pattern(
        _vest(ShapeFeature(hem_style="pointed", hem_depth_cm=6.0)), _m(), "modifiers"))
    assert pointed_mod > straight  # the contour actually changed the hem


def test_shape_mode_defaults_to_modifiers():
    # No explicit mode → modifiers path; a pointed shape still lowers the hem.
    straight = _front_max_y(generate_pattern(_vest(ShapeFeature()), _m()))
    pointed = _front_max_y(generate_pattern(
        _vest(ShapeFeature(hem_style="pointed", hem_depth_cm=6.0)), _m()))
    assert pointed > straight
