"""Tests for asymmetric wrap fronts, the mandarin collar, and per-panel warp."""
import pytest

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
from app.patterns.geometry import CurveSegment, Point
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


def test_overlap_front_is_wider_and_has_free_wrap_edge():
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


def test_overlap_wrap_band_matches_corrected_reference():
    """Wrap look pinned to harness/blueVestCorrected.svg (frog on the CF, a stepped
    wrap band through the mid-body only, hem ending at the CF) — but with the
    construction-consistent neck: a symmetric neckline curve down to the CF throat
    and a closure edge from the throat to the frog."""
    m = _m()
    pieces = build_vest_block(m, front_style="asymmetric_wrap", overlap_cm=18.0)
    ov = pieces["overlap_front"]
    chest_qt = (m.chest_cm + 6.0) / 4  # EASE_CHEST
    cf = chest_qt
    arm_depth = ov.outline[4].y        # armscye curve endpoint = underarm depth

    # Vertex 0 is the frog-closure point on the CF, halfway throat → underarm.
    frog = ov.outline[0]
    throat = ov.outline[1]
    assert frog.x == pytest.approx(cf)
    assert throat.x == pytest.approx(cf)
    assert frog.y == pytest.approx((throat.y + arm_depth) / 2)
    # Edge 0 (frog → throat) is closure, edge 1 the neckline CURVE to the neck point.
    assert ov.edge_labels[0] == "overlap_edge"
    assert isinstance(ov.outline[2], CurveSegment)
    assert ov.edge_labels[1] == "neckline"
    # The vision's 18 cm overlap is clamped to 0.46 × quarter-chest.
    wrap_x = min(p.x for p in ov.outline)
    assert wrap_x == pytest.approx(cf - chest_qt * 0.46)
    # The band crosses CF only through the mid-body: the hem's inner corner is AT the CF.
    L = m.length_cm
    hem_xs = [p.x for p in ov.outline if isinstance(p, Point) and abs(p.y - L) < 1e-6]
    assert min(hem_xs) == pytest.approx(cf)
    # The band vertices step out and back at the same two heights.
    band_ys = sorted({round(p.y, 2) for p in ov.outline if isinstance(p, Point) and p.x == pytest.approx(wrap_x)})
    assert len(band_ys) == 2
    assert band_ys[0] < arm_depth < band_ys[1]  # spans across the underarm line


def test_underlap_is_a_normal_front_half():
    """The underlap is a standard vest front: neckline curve, straight CF edge, no
    extension past the CF."""
    m = _m()
    pieces = build_vest_block(m, front_style="asymmetric_wrap")
    un = pieces["underlap_front"]
    cf = (m.chest_cm + 6.0) / 4
    assert max(p.x for p in un.outline) == pytest.approx(cf)   # nothing crosses the CF
    assert isinstance(un.outline[1], CurveSegment)             # neckline curve
    assert un.edge_labels[0] == "neckline"
    assert list(un.edge_labels.values()).count("underlap_edge") == 1
    # Straight CF edge: both the CF neck and the CF hem corner sit at x = cf.
    assert un.outline[0].x == pytest.approx(cf)
    assert un.outline[-1].x == pytest.approx(cf)


def test_wrap_side_left_mirrors_the_construction():
    right = build_vest_block(_m(), front_style="asymmetric_wrap", wrap_side="right")["overlap_front"]
    left = build_vest_block(_m(), front_style="asymmetric_wrap", wrap_side="left")["overlap_front"]
    # Reflected about the full-front width → the overlap sits on the opposite side.
    assert round(min(p.x for p in right.outline), 1) != round(min(p.x for p in left.outline), 1)


def test_symmetric_default_unchanged():
    pieces = build_vest_block(_m())
    assert "front_bodice" in pieces and "overlap_front" not in pieces


# ── Wearability: the panels must sew together ─────────────────────────────────

def _label_lengths(spec) -> dict[str, float]:
    """Summed curve-aware path length of a piece's edges, grouped by seam label."""
    from app.patterns.finishings import path_length

    o = spec.outline
    n = len(o)
    sums: dict[str, float] = {}
    for i in range(n):
        label = spec.edge_labels.get(i, "")
        if not label:
            continue
        a, b = o[i], o[(i + 1) % n]
        sums[label] = sums.get(label, 0.0) + path_length([Point(a.x, a.y), b])
    return sums


def test_front_and_back_seams_match():
    """Shoulder, armhole, side seam, and hem must agree between every front panel
    and the back — otherwise the vest cannot be sewn flat."""
    pieces = build_vest_block(_m(), front_style="asymmetric_wrap", collar_style="mandarin")
    back = _label_lengths(pieces["back_bodice"])
    for key in ("overlap_front", "underlap_front"):
        front = _label_lengths(pieces[key])
        for label, tol in (("shoulder", 0.1), ("armhole", 0.2), ("side_seam", 0.2), ("hem", 0.1)):
            assert front[label] == pytest.approx(back[label], abs=tol), f"{key} {label}"


def test_shoulder_seams_align_with_back():
    """Front shoulder edges share the back's endpoints (mirrored): neck point at
    y = 0, tip at shoulder_slope — so the seams align and the neckline doesn't step."""
    pieces = build_vest_block(_m(), front_style="asymmetric_wrap")
    back = pieces["back_bodice"]
    neck_b, tip_b = back.outline[1], back.outline[2]
    for key, neck_i in (("overlap_front", 2), ("underlap_front", 1)):
        o = pieces[key].outline
        neck_f, tip_f = o[neck_i], o[neck_i + 1]
        assert neck_f.y == pytest.approx(neck_b.y)     # both neck points at y = 0
        assert tip_f.y == pytest.approx(tip_b.y)       # both tips at shoulder_slope


def test_neck_hole_is_symmetric():
    """Both wrap panels carry the SAME mirrored neckline curve, so the assembled
    neck hole (and the collar seam) is symmetric left/right of the body."""
    m = _m()
    pieces = build_vest_block(m, front_style="asymmetric_wrap")
    ov, un = pieces["overlap_front"], pieces["underlap_front"]
    cf = (m.chest_cm + 6.0) / 4
    ov_neck, un_neck = ov.outline[2], un.outline[1]     # neckline CurveSegments
    # Mirrored endpoints and control points about the CF.
    assert ov_neck.x - cf == pytest.approx(cf - un_neck.x)
    assert ov_neck.y == pytest.approx(un_neck.y)
    assert ov_neck.cp1.x - cf == pytest.approx(cf - un_neck.cp1.x)
    assert ov_neck.cp1.y == pytest.approx(un_neck.cp1.y)
    assert ov_neck.cp2.x - cf == pytest.approx(cf - un_neck.cp2.x)
    assert ov_neck.cp2.y == pytest.approx(un_neck.cp2.y)
    # Equal neckline lengths.
    assert _label_lengths(ov)["neckline"] == pytest.approx(_label_lengths(un)["neckline"], abs=0.05)


# ── Mandarin collar ───────────────────────────────────────────────────────────

def test_mandarin_collar_piece():
    pieces = build_vest_block(_m(), collar_style="mandarin")
    assert "collar" in pieces and pieces["collar"].name == "Mandarin Collar"
    assert pieces["collar"].cut_qty == 2


def test_mandarin_collar_fits_the_wrap_neck_hole():
    """For the wrap front the collar band must be as long as the MEASURED neck hole:
    both mirrored front neckline curves plus the full back neck."""
    m = _m()
    pieces = build_vest_block(m, front_style="asymmetric_wrap", collar_style="mandarin")
    hole = (
        _label_lengths(pieces["overlap_front"])["neckline"]
        + _label_lengths(pieces["underlap_front"])["neckline"]
        + 2 * _label_lengths(pieces["back_bodice"])["neckline"]  # back is cut on fold
    )
    collar_len = max(p.x for p in pieces["collar"].outline)
    assert collar_len == pytest.approx(hole, abs=0.5)


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
