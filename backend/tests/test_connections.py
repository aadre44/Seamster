"""Seam-connection pairing tests (T2 — codebase-review-tasks.md, review finding A3).

_compute_connections must pair same-label edges 1:1 per piece pair, not as a
cross-product: the trouser side seam spans 4 edges per leg, which previously
produced 4x4 = 16 connections for one physical seam.
"""
from collections import Counter

from app.models.features import ClosureFeature, DartFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements
from app.patterns.engine import _compute_connections, generate_pattern


def _measurements(**overrides) -> Measurements:
    defaults = dict(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=100.0,
        chest_cm=90.0, shoulder_width_cm=38.0, arm_length_cm=60.0,
        inseam_cm=76.0, seam_allowance_cm=1.5,
    )
    defaults.update(overrides)
    return Measurements(**defaults)


def _trouser_psnap(details=None):
    f = GarmentFeatures(
        garment_type=GarmentType.TROUSERS, silhouette="regular",
        length_category="full_length",
        closure=ClosureFeature(type="center_front_zip", position="center_front"),
        darts=DartFeature(front=1, back=2),
        details=details or [], confidence=0.9,
    )
    return generate_pattern(f, _measurements())


def _piece(psnap, name):
    return next(p for p in psnap["pieces"] if p["name"] == name)


def _connections_between(psnap, label, name_a, name_b):
    ida, idb = _piece(psnap, name_a)["id"], _piece(psnap, name_b)["id"]
    return [
        c for c in psnap["connections"]
        if c["label"] == label
        and {c["from"]["pieceId"], c["to"]["pieceId"]} == {ida, idb}
    ]


def _edges_with_label(psnap, piece_name, label):
    piece = _piece(psnap, piece_name)
    ids = set(piece["elementIds"])
    return [
        e for e in psnap["elements"]
        if e["id"] in ids and e.get("seamLabel") == label and not e.get("isFold")
    ]


def _edge_by_id(psnap, edge_id):
    return next(e for e in psnap["elements"] if e["id"] == edge_id)


def _chord(elem):
    dx = elem["end"]["x"] - elem["start"]["x"]
    dy = elem["end"]["y"] - elem["start"]["y"]
    return (dx * dx + dy * dy) ** 0.5


# ── Trousers: the multi-edge seam that motivated the fix ──────────────────────

def test_trouser_side_seam_pairs_one_to_one():
    psnap = _trouser_psnap()
    n_front = len(_edges_with_label(psnap, "Front Leg", "side_seam"))
    n_back = len(_edges_with_label(psnap, "Back Leg", "side_seam"))
    assert n_front == 4 and n_back == 4  # sanity: the seam really is multi-edge

    conns = _connections_between(psnap, "side_seam", "Front Leg", "Back Leg")
    # One connection per physical edge pair — not 4x4 = 16
    assert len(conns) == 4


def test_no_edge_connects_twice_to_the_same_piece_under_one_label():
    psnap = _trouser_psnap()
    for label in ("side_seam", "inseam", "crotch"):
        usage = Counter()
        for c in psnap["connections"]:
            if c["label"] != label:
                continue
            # An edge may appear in at most ONE connection per (label, other piece)
            usage[(c["from"]["edgeId"], c["to"]["pieceId"])] += 1
            usage[(c["to"]["edgeId"], c["from"]["pieceId"])] += 1
        assert usage and max(usage.values()) == 1


def test_paired_side_seam_segments_correspond_physically():
    """The k-th front segment must pair with the k-th back segment (waist->hip,
    hip->thigh, ...). Corresponding sewn segments have near-equal lengths, while
    a cross-pairing (waist segment against ankle segment) differs wildly."""
    psnap = _trouser_psnap()
    for c in _connections_between(psnap, "side_seam", "Front Leg", "Back Leg"):
        len_a = _chord(_edge_by_id(psnap, c["from"]["edgeId"]))
        len_b = _chord(_edge_by_id(psnap, c["to"]["edgeId"]))
        assert abs(len_a - len_b) < max(len_a, len_b) * 0.5, (
            f"paired side_seam segments differ too much: {len_a:.1f} vs {len_b:.1f} cm"
        )


def test_inseam_pairs_one_to_one():
    psnap = _trouser_psnap()
    conns = _connections_between(psnap, "inseam", "Front Leg", "Back Leg")
    assert len(conns) == 2  # ankle->knee and knee->crotch, not 2x2


# ── Single-edge labels keep their previous behaviour ──────────────────────────

def test_single_edge_labels_still_connect():
    psnap = _trouser_psnap()
    assert len(_connections_between(psnap, "crotch", "Front Leg", "Back Leg")) == 1
    # Waist connects front<->back and each leg to the waistband (single edges each)
    waist = [c for c in psnap["connections"] if c["label"] == "waist"]
    assert len(waist) >= 1
    pair_counts = Counter(
        frozenset((c["from"]["pieceId"], c["to"]["pieceId"])) for c in waist
    )
    assert max(pair_counts.values()) == 1  # one waist connection per piece pair


# ── Orientation: reversed traversal is detected by length mismatch ────────────

def test_reversed_outline_direction_is_corrected():
    piece_a = {"id": "PA", "elementIds": ["a1", "a2", "a3"]}
    piece_b = {"id": "PB", "elementIds": ["b1", "b2", "b3"]}

    def line(eid, pid, x1, y1, x2, y2):
        return {
            "id": eid, "type": "line", "pieceId": pid, "seamLabel": "side_seam",
            "start": {"x": x1, "y": y1}, "end": {"x": x2, "y": y2},
        }

    # Piece A traverses top->bottom: segments of length 10, 20, 40.
    a_edges = [
        line("a1", "PA", 0, 0, 0, 10),
        line("a2", "PA", 0, 10, 0, 30),
        line("a3", "PA", 0, 30, 0, 70),
    ]
    # Piece B traverses bottom->top: lengths 40, 20, 10 (reverse order).
    b_edges = [
        line("b1", "PB", 5, 70, 5, 30),
        line("b2", "PB", 5, 30, 5, 10),
        line("b3", "PB", 5, 10, 5, 0),
    ]
    conns = _compute_connections(a_edges + b_edges, [piece_a, piece_b])
    assert len(conns) == 3
    matched = {c["from"]["edgeId"]: c["to"]["edgeId"] for c in conns}
    # Length-rank pairing: 10<->10, 20<->20, 40<->40
    assert matched == {"a1": "b3", "a2": "b2", "a3": "b1"}


def test_unequal_edge_counts_leave_extras_unconnected():
    piece_a = {"id": "PA", "elementIds": ["a1"]}
    piece_b = {"id": "PB", "elementIds": ["b1", "b2"]}
    elems = [
        {"id": "a1", "type": "line", "pieceId": "PA", "seamLabel": "hem",
         "start": {"x": 0, "y": 0}, "end": {"x": 10, "y": 0}},
        {"id": "b1", "type": "line", "pieceId": "PB", "seamLabel": "hem",
         "start": {"x": 0, "y": 5}, "end": {"x": 10, "y": 5}},
        {"id": "b2", "type": "line", "pieceId": "PB", "seamLabel": "hem",
         "start": {"x": 10, "y": 5}, "end": {"x": 20, "y": 5}},
    ]
    conns = _compute_connections(elems, [piece_a, piece_b])
    assert len(conns) == 1  # a1<->b1; b2 stays unmatched (no cross-product)
