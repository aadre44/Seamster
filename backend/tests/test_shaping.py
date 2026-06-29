"""Tests for the garment-shape layer (hem contour, taper, warp) and mode dispatch."""
import math

from app.models.features import (
    ClosureFeature,
    GarmentFeatures,
    GarmentType,
    ShapeFeature,
    SilhouettePath,
)
from app.models.measurements import Measurements
from app.patterns.geometry import CurveSegment, Point
from app.patterns.shaping import (
    apply_front_cut,
    apply_shape,
    apply_taper,
    reshape_hem,
    reshape_side_vent,
    warp_to_silhouette,
)
from app.patterns.vests import build_vest_block


def _m() -> Measurements:
    return Measurements(
        waist_cm=80.0, hip_cm=98.0, waist_to_hip_cm=21.0, length_cm=62.0,
        chest_cm=96.0, shoulder_width_cm=40.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


def _front() -> "PieceSpec":  # noqa: F821
    return build_vest_block(_m(), fit_style="boxy", neckline="notched_v")["front_bodice"]


def _hem_corners(spec):
    """Return (side_corner, cf_corner) of the hem edge."""
    k = next(i for i, lbl in spec.edge_labels.items() if lbl == "hem")
    n = len(spec.outline)
    return spec.outline[k], spec.outline[(k + 1) % n]


# ── reshape_hem ───────────────────────────────────────────────────────────────

def test_pointed_drops_cf_below_hemline():
    spec = _front()
    _, cf_before = _hem_corners(spec)
    reshape_hem(spec, "pointed", depth=5.0)
    _, cf_after = _hem_corners(spec)
    assert math.isclose(cf_after.y, cf_before.y + 5.0, rel_tol=1e-6)
    assert math.isclose(cf_after.x, 0.0, abs_tol=1e-6)  # apex stays on the CF fold


def test_curved_scoop_makes_hem_a_curve():
    spec = _front()
    assert not any(lbl == "hem" and isinstance(spec.outline[(i + 1) % len(spec.outline)], CurveSegment)
                   for i, lbl in spec.edge_labels.items())
    reshape_hem(spec, "curved_scoop", depth=4.0)
    _, cf = _hem_corners(spec)
    assert isinstance(cf, CurveSegment)


def test_high_low_offsets_cf_vs_side():
    spec = _front()
    reshape_hem(spec, "high_low", depth=0.0, high_low=6.0)
    side, cf = _hem_corners(spec)
    assert not math.isclose(side.y, cf.y, abs_tol=1e-6)


def test_cutaway_curves_corner_and_raises_cf():
    spec = _front()
    _, cf_before = _hem_corners(spec)
    reshape_hem(spec, "cutaway", depth=5.0)
    _, cf_after = _hem_corners(spec)
    assert isinstance(cf_after, CurveSegment)
    assert cf_after.y < cf_before.y  # corner raised


def test_straight_is_a_noop():
    spec = _front()
    before = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    reshape_hem(spec, "straight", depth=5.0)
    after = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    assert before == after


# ── apply_taper ───────────────────────────────────────────────────────────────

def test_hem_sweep_moves_side_seam_out_at_hem():
    spec = _front()
    side_before_x = _hem_corners(spec)[0].x  # capture the value (taper mutates in place)
    apply_taper(spec, waist_taper=0.0, hem_sweep=6.0, waist_y=46.0)
    side_after_x = _hem_corners(spec)[0].x
    assert side_after_x > side_before_x  # hem swept outward


def test_taper_noop_when_zero():
    spec = _front()
    before = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    apply_taper(spec, waist_taper=0.0, hem_sweep=0.0, waist_y=46.0)
    after = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    assert before == after


# ── reshape_side_vent ─────────────────────────────────────────────────────────

def _back():
    return build_vest_block(_m(), fit_style="boxy", neckline="notched_v")["back_bodice"]


def test_side_vent_splits_seam_and_opens_lower_part():
    spec = _front()
    n_before = len(spec.outline)
    side_seams_before = sum(1 for v in spec.edge_labels.values() if v == "side_seam")
    reshape_side_vent(spec, height=10.0)
    # One vertex inserted; the open vent edge is unlabelled (not auto-connected).
    assert len(spec.outline) == n_before + 1
    assert "" in spec.edge_labels.values()
    # The sewn upper side seam survives, and the hem is still present.
    assert sum(1 for v in spec.edge_labels.values() if v == "side_seam") == side_seams_before
    assert "hem" in spec.edge_labels.values()
    assert "vent" in (spec.notes or "")


def test_side_vent_noop_when_zero():
    spec = _front()
    before = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    reshape_side_vent(spec, height=0.0)
    assert before == [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]


def test_side_vent_applies_to_back_too():
    spec = _back()
    n_before = len(spec.outline)
    reshape_side_vent(spec, height=8.0)
    assert len(spec.outline) == n_before + 1


# ── apply_front_cut ───────────────────────────────────────────────────────────

def test_front_cut_opens_front_off_fold():
    spec = _front()
    assert spec.on_fold is True
    apply_front_cut(spec, "cutaway", depth=8.0)
    assert spec.on_fold is False and spec.cut_qty == 2
    # The CF hem corner swung outward (gap), and a cutaway curve was inserted.
    assert any(isinstance(v, CurveSegment) for v in spec.outline)
    assert "center_front" in spec.edge_labels.values()


def test_front_cut_skips_back_panel():
    spec = _back()  # has center_back, not center_front
    before_fold = spec.on_fold
    apply_front_cut(spec, "cutaway", depth=8.0)
    assert spec.on_fold == before_fold  # untouched


def test_front_cut_closed_is_noop():
    spec = _front()
    before = [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    apply_front_cut(spec, "closed", depth=8.0)
    assert before == [(round(p.x, 3), round(p.y, 3)) for p in spec.outline]
    assert spec.on_fold is True


# ── warp_to_silhouette ────────────────────────────────────────────────────────

def test_warp_keeps_cf_fold_and_stays_simple():
    spec = _front()
    # A flared hull: side-top → side-hem (wider) → CF hem.
    warp_to_silhouette(spec, [(1.0, 0.0), (1.2, 1.0), (0.0, 1.0)])
    # CF fold preserved: the closing vertex sits on x≈0, and labels still close the loop.
    assert math.isclose(spec.outline[-1].x, 0.0, abs_tol=0.2)
    assert "center_front" in spec.edge_labels.values()
    assert "hem" in spec.edge_labels.values()
    # All x ≥ 0 (no fold crossing).
    assert all(p.x >= -1e-6 for p in spec.outline)


# ── Dispatch via apply_shape ──────────────────────────────────────────────────

def _vest_feats(shape: ShapeFeature | None, path: SilhouettePath | None = None) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=GarmentType.VEST, silhouette="boxy", length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        neckline="notched_v", shape=shape, silhouette_path=path, confidence=0.9,
    )


def test_modifiers_mode_applies_hem_and_taper():
    pieces = build_vest_block(_m(), fit_style="boxy", neckline="notched_v")
    feats = _vest_feats(ShapeFeature(hem_style="pointed", hem_depth_cm=5.0))
    apply_shape(pieces, feats, _m(), mode="modifiers")
    _, cf = _hem_corners(pieces["front_bodice"])
    assert cf.y > 62.0  # CF dropped below the hemline


def test_fit_params_mode_is_noop_postbuild():
    pieces = build_vest_block(_m(), fit_style="boxy", neckline="notched_v")
    before = [(round(p.x, 3), round(p.y, 3)) for p in pieces["front_bodice"].outline]
    feats = _vest_feats(ShapeFeature(hem_style="pointed", hem_depth_cm=5.0))
    apply_shape(pieces, feats, _m(), mode="fit_params")  # baked at build time, not here
    after = [(round(p.x, 3), round(p.y, 3)) for p in pieces["front_bodice"].outline]
    assert before == after


def test_modifiers_mode_noop_without_shape():
    pieces = build_vest_block(_m(), fit_style="boxy", neckline="notched_v")
    before = [(round(p.x, 3), round(p.y, 3)) for p in pieces["front_bodice"].outline]
    apply_shape(pieces, _vest_feats(None), _m(), mode="modifiers")
    after = [(round(p.x, 3), round(p.y, 3)) for p in pieces["front_bodice"].outline]
    assert before == after


def test_modifiers_apply_vent_and_front_cut_together():
    pieces = build_vest_block(_m(), fit_style="fitted", neckline="v_neck")
    feats = _vest_feats(ShapeFeature(side_vent_cm=9.0, front_cut="cutaway", front_cut_depth_cm=7.0))
    apply_shape(pieces, feats, _m(), mode="modifiers")
    front, back = pieces["front_bodice"], pieces["back_bodice"]
    # Front opened off the fold; back vented but still on the fold.
    assert front.on_fold is False and front.cut_qty == 2
    assert back.on_fold is True
    # Both panels gained a vent (an unlabelled open edge).
    assert "" in front.edge_labels.values() and "" in back.edge_labels.values()


def test_trim_pieces_are_not_warped_or_reshaped():
    # A binding piece has no hem/armhole labels → shape layer must skip it untouched.
    pieces = build_vest_block(_m(), binding_edges=("neckline",))
    binding_before = [(round(p.x, 3), round(p.y, 3)) for p in pieces["neck_binding"].outline]
    feats = _vest_feats(ShapeFeature(hem_style="pointed", hem_depth_cm=5.0))
    apply_shape(pieces, feats, _m(), mode="modifiers")
    binding_after = [(round(p.x, 3), round(p.y, 3)) for p in pieces["neck_binding"].outline]
    assert binding_before == binding_after
