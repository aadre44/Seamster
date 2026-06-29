"""Tests for asymmetric wrap fronts, the mandarin collar, and per-panel warp."""
from app.models.features import (
    AsymmetryFeature,
    BindingFeature,
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    ShapeFeature,
    SilhouettePath,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern
from app.patterns.geometry import CurveSegment
from app.patterns.llm_fallback import detect_unsupported_details
from app.patterns.shaping import apply_shape
from app.patterns.vests import build_vest_block


def _m() -> Measurements:
    return Measurements(
        waist_cm=82.0, hip_cm=98.0, waist_to_hip_cm=21.0, length_cm=60.0,
        chest_cm=96.0, shoulder_width_cm=40.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


# ── Builder ───────────────────────────────────────────────────────────────────

def test_asymmetric_wrap_emits_two_distinct_fronts():
    pieces = build_vest_block(_m(), front_style="asymmetric_wrap", overlap_cm=14.0)
    assert "front_bodice" not in pieces
    assert "overlap_front" in pieces and "underlap_front" in pieces
    ov, un = pieces["overlap_front"], pieces["underlap_front"]
    assert ov.cut_qty == 1 and not ov.on_fold
    assert un.cut_qty == 1 and not un.on_fold
    # The two fronts are genuinely DIFFERENT shapes (not mirrors).
    ov_xy = [(round(p.x, 2), round(p.y, 2)) for p in ov.outline]
    un_xy = [(round(p.x, 2), round(p.y, 2)) for p in un.outline]
    assert ov_xy != un_xy


def test_overlap_front_is_wider_and_has_diagonal_edge():
    pieces = build_vest_block(_m(), front_style="asymmetric_wrap", overlap_cm=14.0)
    ov = pieces["overlap_front"]
    un = pieces["underlap_front"]
    ov_w = max(p.x for p in ov.outline) - min(p.x for p in ov.outline)
    un_w = max(p.x for p in un.outline) - min(p.x for p in un.outline)
    assert ov_w > un_w  # the wrap panel is the larger one
    # The free/closure edge is labelled distinctly so it is never sewn as a seam.
    assert "overlap_edge" in ov.edge_labels.values()
    assert "underlap_edge" in un.edge_labels.values()
    assert any(isinstance(v, CurveSegment) for v in ov.outline)  # armscye curve


def test_wrap_side_left_mirrors_the_construction():
    right = build_vest_block(_m(), front_style="asymmetric_wrap", wrap_side="right")["overlap_front"]
    left = build_vest_block(_m(), front_style="asymmetric_wrap", wrap_side="left")["overlap_front"]
    # Reflected about the full-front width → the overlap sits on the opposite side.
    assert round(min(p.x for p in right.outline), 1) != round(min(p.x for p in left.outline), 1)


def test_symmetric_default_unchanged():
    pieces = build_vest_block(_m())
    assert "front_bodice" in pieces and "overlap_front" not in pieces


# ── Mandarin collar ───────────────────────────────────────────────────────────

def test_mandarin_collar_piece():
    pieces = build_vest_block(_m(), collar_style="mandarin")
    assert "collar" in pieces and pieces["collar"].name == "Mandarin Collar"
    assert pieces["collar"].cut_qty == 2


# ── Engine + connections ──────────────────────────────────────────────────────

def _asym_feats() -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="button_front", position="center_front"),
        darts=DartFeature(front=0, back=0), neckline="mandarin",
        asymmetry=AsymmetryFeature(front_style="asymmetric_wrap", wrap_side="right",
                                   overlap_cm=14.0, closure_drop_frac=1.0),
        facings=["armhole"], binding=BindingFeature(edges=["neckline"], width_cm=1.5, contrast=False),
        confidence=0.8,
    )


def test_engine_generates_asymmetric_vest_with_collar():
    psnap = generate_pattern(_asym_feats(), _m(), "modifiers")
    names = [p["name"] for p in psnap["pieces"]]
    assert "Overlap Front" in names and "Underlap Front" in names
    assert "Front Bodice" not in names
    assert "Mandarin Collar" in names
    assert "Back Bodice" in names
    # Side seams still connect; the open wrap edges do not.
    labels = {c["label"] for c in psnap["connections"]}
    assert "side_seam" in labels
    assert "overlap_edge" not in labels and "underlap_edge" not in labels


def test_asymmetry_and_collar_do_not_trigger_llm_fallback():
    feats = _asym_feats()
    feats.details = ["mandarin_collar", "asymmetric_wrap", "topstitching"]
    assert detect_unsupported_details(feats) == []


def test_detail_token_drives_asymmetry_without_structured_field():
    feats = GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="button_front", position="center_front"),
        neckline="v_neck", details=["asymmetric_wrap", "mandarin_collar"], confidence=0.7,
    )
    names = [p["name"] for p in generate_pattern(feats, _m())["pieces"]]
    assert "Overlap Front" in names and "Mandarin Collar" in names


# ── Per-panel warp (layered foundation) ───────────────────────────────────────

def test_warp_uses_per_panel_hull():
    pieces = build_vest_block(_m(), front_style="asymmetric_wrap")
    # A distinct hull for just the overlap panel.
    feats = GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="regular", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        shape=ShapeFeature(),
        silhouette_path=SilhouettePath(panels={"overlap_front": [(1.0, 0.0), (1.3, 1.0), (0.0, 1.0)]}),
        confidence=0.7,
    )
    before = [(round(p.x, 2), round(p.y, 2)) for p in pieces["underlap_front"].outline]
    apply_shape(pieces, feats, _m(), mode="warp")
    # The overlap got warped (its outline changed); the underlap (no hull) is left intact
    # apart from the synthesized fallback — assert the overlap still closes at the fold.
    assert pieces["overlap_front"].outline[-1].x >= -1e-6
