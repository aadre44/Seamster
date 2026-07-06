"""Tests for the sleeveless vest block and its engine wiring."""
import math

from app.models.features import (
    BindingFeature,
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    WeltPocketFeature,
)
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern
from app.patterns.geometry import CurveSegment
from app.patterns.llm_fallback import detect_unsupported_details
from app.patterns.vests import build_vest_block


def _m() -> Measurements:
    return Measurements(
        waist_cm=80.0, hip_cm=98.0, waist_to_hip_cm=21.0, length_cm=62.0,
        chest_cm=96.0, shoulder_width_cm=40.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


def _piece_names(psnap: dict) -> list[str]:
    return [p["name"] for p in psnap["pieces"]]


# ── Block-level geometry ──────────────────────────────────────────────────────

def test_block_builds_front_and_back_no_sleeve():
    pieces = build_vest_block(_m(), fit_style="boxy", neckline="notched_v")
    assert set(pieces) == {"front_bodice", "back_bodice"}
    assert all("Sleeve" not in p.name for p in pieces.values())


def test_notched_v_has_slit_notch_and_v():
    pieces = build_vest_block(_m(), neckline="notched_v")
    front = pieces["front_bodice"]
    # Three neckline edges = 4 neck vertices: CF-bottom, slit-top, notch, shoulder neck.
    neck_edges = [i for i, lbl in front.edge_labels.items() if lbl == "neckline"]
    assert len(neck_edges) == 3
    # CF deepest point sits on the fold (x≈0) at a positive depth (the V bottom).
    cf_pt = front.outline[0]
    assert math.isclose(cf_pt.x, 0.0, abs_tol=1e-6) and cf_pt.y > 0.0
    # The narrow slit: the first edge rises steeply (small Δx, larger Δy).
    a, b = front.outline[0], front.outline[1]
    assert abs(b.x - a.x) < (a.y - b.y), "CF slit should be near-vertical"


def test_split_v_has_no_notch_step():
    pieces = build_vest_block(_m(), neckline="split_v")
    front = pieces["front_bodice"]
    neck_edges = [i for i, lbl in front.edge_labels.items() if lbl == "neckline"]
    assert len(neck_edges) == 2  # slit + straight V, no notch vertex


def test_front_uses_a_curved_armscye():
    front = build_vest_block(_m())["front_bodice"]
    assert any(isinstance(v, CurveSegment) for v in front.outline), "armscye should be a curve"


# ── Optional finishing pieces ─────────────────────────────────────────────────

def test_binding_strip_matches_neckline_run():
    from app.patterns.finishings import path_length

    pieces = build_vest_block(_m(), binding_edges=("neckline",), binding_width=1.0)
    assert "neck_binding" in pieces
    strip = pieces["neck_binding"]
    xs = [p.x for p in strip.outline]
    longer = max(xs) - min(xs)
    # Reconstruct the expected neck run: 2× front neck path + 2× back neck width.
    front = build_vest_block(_m())["front_bodice"]
    neck_pts = [v for i, v in enumerate(front.outline) if front.edge_labels.get(i) == "neckline"]
    neck_pts = front.outline[:4]  # CF-bottom, slit-top, notch, shoulder neck
    back_neck_w = 96.0 / 10 + 1.0
    expected = 2 * path_length(neck_pts) + 2 * back_neck_w
    assert math.isclose(longer, expected + 2.0, rel_tol=1e-3)


def test_facings_and_welts_emitted_on_request():
    pieces = build_vest_block(
        _m(), facings=("armhole", "hem"), welt_count=2, welt_width=14.0,
    )
    assert "armhole_facing" in pieces and pieces["armhole_facing"].cut_qty == 4
    assert "hem_facing" in pieces
    assert "welt_strip" in pieces and "welt_pocket_bag" in pieces
    assert pieces["welt_strip"].cut_qty == 2


# ── Engine wiring ─────────────────────────────────────────────────────────────

def _reference_vest_features() -> GarmentFeatures:
    """The reference garment: boxy notched split-V vest, contrast neckline binding,
    faced armholes/hem, two lower-front welt pockets."""
    return GarmentFeatures(
        garment_type=GarmentType.VEST,
        silhouette="boxy",
        length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        darts=DartFeature(front=0, back=0),
        neckline="notched_v",
        binding=BindingFeature(edges=["neckline"], width_cm=0.8, contrast=True),
        facings=["armhole", "hem"],
        welt_pockets=[WeltPocketFeature(position="lower_front", width_cm=14.0, count=2)],
        confidence=0.9,
        notes="boxy wool vest with a dark contrast-bound notched split V and two lower welts",
    )


def test_engine_generates_full_reference_vest():
    psnap = generate_pattern(_reference_vest_features(), _m())
    names = _piece_names(psnap)
    assert "Front Bodice" in names and "Back Bodice" in names
    assert "Sleeve" not in names
    assert "Neckline Binding" in names
    assert "Armhole Facing" in names and "Hem Facing" in names
    assert "Welt Strip" in names and "Welt Pocket Bag" in names
    # Shoulder + side seams wire up between Front and Back.
    labels = {c["label"] for c in psnap["connections"]}
    assert {"shoulder", "side_seam"} <= labels


def test_vest_does_not_trigger_llm_fallback():
    # All vest finishes are structured fields — nothing should fall through to the LLM.
    assert detect_unsupported_details(_reference_vest_features()) == []


def test_edge_in_both_binding_and_facings_keeps_facing_only():
    # A contradictory analysis (blueVest run): binding AND facing claimed for the
    # same edges. The facing must win; no binding strips for those edges.
    feats = _reference_vest_features()
    feats.binding = BindingFeature(edges=["neckline", "armhole"], width_cm=1.0, contrast=True)
    feats.facings = ["neckline", "armhole"]
    names = _piece_names(generate_pattern(feats, _m()))
    assert "Neckline Facing" in names and "Armhole Facing" in names
    assert "Neckline Binding" not in names and "Armhole Binding" not in names


def test_vision_contours_do_not_duplicate_engine_pieces():
    # Forced-contour debug mode returns a contour for every visible piece; those
    # that re-trace pieces the engine drafted must not land on the canvas twice.
    from app.models.features import ContourPoint, PieceContour

    unit_square = [
        ContourPoint(x=0.0, y=0.0), ContourPoint(x=1.0, y=0.0),
        ContourPoint(x=1.0, y=1.0), ContourPoint(x=0.0, y=1.0),
    ]
    feats = _reference_vest_features()
    feats.piece_contours = [
        PieceContour(detail="back_panel", name="Back Panel",
                     points=unit_square, width_frac=0.95, confidence=0.75),
        PieceContour(detail="frog_button_closure", name="Chinese Frog Button / Knot Closure",
                     points=unit_square, width_frac=0.08, confidence=0.88),
    ]
    names = _piece_names(generate_pattern(feats, _m()))
    assert "Back Bodice" in names
    assert "Back Panel" not in names                       # dedupe against the engine
    assert all("Frog" not in n for n in names)             # notions are never pieces


def test_detail_tokens_drive_finishes_without_structured_fields():
    feats = GarmentFeatures(
        garment_type=GarmentType.VEST,
        silhouette="boxy",
        length_category="hip_length",
        closure=ClosureFeature(type="none", position="center_front"),
        neckline="split_v",
        details=["neckline_binding", "armhole_facing", "welt_pockets"],
        confidence=0.8,
    )
    names = _piece_names(generate_pattern(feats, _m()))
    assert "Neckline Binding" in names
    assert "Armhole Facing" in names
    assert "Welt Strip" in names
    # registered tokens must not also produce duplicate LLM pieces
    assert detect_unsupported_details(feats) == []
