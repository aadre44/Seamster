"""Tests for notes-based pocket-shape inference in the vision analyzer."""
from app.models.features import ClosureFeature, DartFeature, GarmentFeatures, GarmentType
from app.vision.analyzer import _infer_pockets_from_notes


def _features(gtype, details, notes) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=gtype, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0),
        details=list(details), notes=notes, confidence=0.9,
    )


def test_infers_pointed_pocket_for_shirt():
    """A tee whose notes describe a pointed chest pocket gains pocket_pointed."""
    f = _features(GarmentType.SHIRT, ["chest_pocket"], "patch chest pocket that comes to a point at the bottom")
    _infer_pockets_from_notes(f)
    assert "pocket_pointed" in f.details


def test_infers_rounded_pocket():
    f = _features(GarmentType.JACKET, ["patch_pockets"], "patch pockets with rounded lower corners")
    _infer_pockets_from_notes(f)
    assert "pocket_rounded" in f.details


def test_does_not_infer_shape_without_patch_pocket():
    f = _features(GarmentType.SHIRT, ["topstitching"], "the hem comes to a point")
    _infer_pockets_from_notes(f)
    assert not any(d.startswith("pocket_") for d in f.details)


def test_explicit_shape_token_not_overridden():
    f = _features(GarmentType.SHIRT, ["chest_pocket", "pocket_curved"], "pointed chevron pocket")
    _infer_pockets_from_notes(f)
    assert "pocket_curved" in f.details
    assert "pocket_pointed" not in f.details  # an explicit token wins
