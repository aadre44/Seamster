"""Trim seams and pocket placements (app/patterns/attachments.py).

Trims are sewn along paths of host edges: every connection pairs a stretch of
one trim element with a stretch of one host element, and the stretches of a
trim edge must tile it without overlapping. Pockets must land on their host.
"""
import math

from fastapi.testclient import TestClient

from app.main import app
from app.models.features import ClosureFeature, GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.engine import _edge_length, generate_pattern

M = Measurements(waist_cm=74, hip_cm=98, waist_to_hip_cm=20, length_cm=100, chest_cm=92,
                 shoulder_width_cm=39, arm_length_cm=58, inseam_cm=77)


def _gen(**kw) -> dict:
    return generate_pattern(GarmentFeatures(confidence=1.0, **kw), M)


def trousers() -> dict:
    return _gen(garment_type="trousers", silhouette="straight", length_category="full",
                closure=ClosureFeature(type="button_fly", position="center_front"),
                details=["fly_shield", "side_pockets", "patch_pockets"])


def shirt() -> dict:
    return _gen(garment_type="shirt", silhouette="fitted", length_category="hip", sleeve_length="long",
                closure=ClosureFeature(type="button_front", position="center_front"),
                details=["collar", "cuffs", "chest_pocket"])


def jacket() -> dict:
    return _gen(garment_type="jacket", silhouette="boxy", length_category="hip", sleeve_length="long",
                closure=ClosureFeature(type="button_front", position="center_front"),
                details=["collar", "welt_pockets", "chest_pocket"])


def _piece(psnap: dict, name: str) -> dict:
    return next(p for p in psnap["pieces"] if p["name"] == name)


def _seams(psnap: dict, name: str) -> list[dict]:
    pid = _piece(psnap, name)["id"]
    return [c for c in psnap["connections"] if pid in (c["from"]["pieceId"], c["to"]["pieceId"])]


def _elements(psnap: dict) -> dict:
    return {e["id"]: e for e in psnap["elements"]}


def _host(psnap: dict, c: dict) -> str:
    return next(p["name"] for p in psnap["pieces"] if p["id"] == c["to"]["pieceId"])


def _tiles(psnap: dict, name: str) -> list[tuple[float, float]]:
    """The trim-edge ranges of a trim's seams, sorted; they must not overlap."""
    ranges = sorted(tuple(c["from"].get("range", [0.0, 1.0])) for c in _seams(psnap, name))
    for (a0, a1), (b0, b1) in zip(ranges, ranges[1:]):
        assert b0 >= a1 - 1e-3, f"{name}: overlapping ranges {ranges}"
    return ranges


def test_fly_facing_left_and_shield_right_on_the_front_cf_from_the_waist():
    p = trousers()
    els = _elements(p)
    for name, side, layer in [("Fly Facing", "left", "inside"), ("Fly Shield", "right", "inside")]:
        (c,) = _seams(p, name)
        assert _host(p, c) == "Front Leg"
        assert els[c["to"]["edgeId"]]["seamLabel"] == "center_front"
        assert c["to"]["side"] == side
        assert _piece(p, name)["layer"] == layer
        # starts at the waist: the CF element's end at the top (smaller y) is covered
        cf = els[c["to"]["edgeId"]]
        lo, hi = c["to"].get("range", [0, 1])
        top_is_start = cf["start"]["y"] < cf["end"]["y"]
        assert (lo < 1e-3) if top_is_start else (hi > 1 - 1e-3)


def test_pocket_bag_inside_the_front_side_seam_and_back_pockets_on_the_back_legs():
    p = trousers()
    (bag,) = _seams(p, "Front Pocket Bag")
    assert _host(p, bag) == "Front Leg" and _piece(p, "Front Pocket Bag")["layer"] == "inside"
    assert _elements(p)[bag["to"]["edgeId"]]["seamLabel"] == "side_seam"
    (pl,) = [x for x in p["placements"] if x["pieceId"] == _piece(p, "Back Pocket")["id"]]
    assert pl["hostId"] == _piece(p, "Back Leg")["id"] and "side" not in pl  # cut 2: both legs
    assert len(pl["stitched"]) == 3  # every edge but the mouth


def test_collar_goes_all_round_the_neckline_without_overlaps():
    p = shirt()
    seams = _seams(p, "Collar")
    assert [(_host(p, c), c["to"].get("side")) for c in seams] == [
        ("Front Bodice", "right"), ("Back Bodice", "right"), ("Back Bodice", "left"), ("Front Bodice", "left")]
    ranges = _tiles(p, "Collar")
    # the collar's seam allowances are left free, one at each end
    assert math.isclose(ranges[0][0], 1 - ranges[-1][1], abs_tol=1e-3)
    assert ranges[0][0] < 0.05
    # back and front shares follow the neckline lengths
    els = _elements(p)
    back = _edge_length(els[seams[1]["to"]["edgeId"]])
    front = _edge_length(els[seams[0]["to"]["edgeId"]])
    share = (ranges[0][1] - ranges[0][0]) / (ranges[-1][1] - ranges[0][0])
    assert math.isclose(share, front / (2 * (front + back)), abs_tol=0.01)


def test_cuff_wraps_both_halves_of_an_on_fold_sleeve():
    p = shirt()
    seams = _seams(p, "Cuff")
    assert [c["to"].get("half") for c in seams] == ["front", "back"]
    assert _tiles(p, "Cuff") == [(0.0, 0.5), (0.5, 1.0)]


def test_half_collar_cut_on_fold_runs_back_then_front():
    p = jacket()
    seams = _seams(p, "Collar")
    assert [_host(p, c) for c in seams] == ["Back Bodice", "Front Bodice"]
    _tiles(p, "Collar")


def test_chest_pocket_on_the_left_front_within_the_bodice():
    p = shirt()
    (pl,) = [x for x in p["placements"] if x["pieceId"] == _piece(p, "Chest Patch Pocket")["id"]]
    host = _piece(p, "Front Bodice")
    assert pl["hostId"] == host["id"] and pl["side"] == "left"
    _assert_inside(p, pl)


def test_welt_bags_hang_under_their_welts():
    p = jacket()
    by_piece = {x["pieceId"]: x for x in p["placements"]}
    for welt, bag in [("Welt Strip", "Welt Pocket Bag"), ("Breast Pocket Welt", "Breast Pocket Bag")]:
        w, b = by_piece[_piece(p, welt)["id"]], by_piece[_piece(p, bag)["id"]]
        assert b["hostId"] == w["hostId"] and _piece(p, bag)["layer"] == "inside"
        assert len(b["stitched"]) == 1  # hangs from its mouth
        _assert_inside(p, w)


def _assert_inside(p: dict, pl: dict) -> None:
    """The placed piece's centre lies inside the host's bounding box."""
    els = _elements(p)
    piece = next(x for x in p["pieces"] if x["id"] == pl["pieceId"])
    host = next(x for x in p["pieces"] if x["id"] == pl["hostId"])
    pts = lambda pc: [(els[i][k]["x"], els[i][k]["y"]) for i in pc["elementIds"] for k in ("start", "end")]  # noqa: E731
    px = [q[0] for q in pts(piece)]
    py = [q[1] for q in pts(piece)]
    cx = (min(px) + max(px)) / 2 + pl["transform"]["dx"]
    cy = (min(py) + max(py)) / 2 + pl["transform"]["dy"]
    hx = [q[0] for q in pts(host)]
    hy = [q[1] for q in pts(host)]
    assert min(hx) < cx < max(hx) and min(hy) < cy < max(hy), (piece["name"], cx, cy)


def test_every_connection_is_marked_inferred():
    for p in (trousers(), shirt()):
        assert all(c["source"] == "inferred" for c in p["connections"])


def test_shell_seams_unchanged_for_a_plain_garment():
    p = _gen(garment_type="skirt", silhouette="a_line", length_category="knee",
             closure=ClosureFeature(type="side_zip", position="left_side"), details=[])
    assert {c["label"] for c in p["connections"]} == {"side_seam"}
    assert p["placements"] == []


def test_endpoint_reinfers_for_a_loaded_pattern():
    p = trousers()
    client = TestClient(app)
    r = client.post("/api/infer-attachments", json={"elements": p["elements"], "pieces": p["pieces"]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["connections"]) == len(p["connections"])
    assert len(body["placements"]) == len(p["placements"])
    assert body["layers"][_piece(p, "Fly Facing")["id"]] == "inside"


def test_endpoint_rejects_malformed_pieces():
    # A collar edge without coordinates: a 422, not a server error.
    elements = [{"id": "x", "type": "line", "pieceId": "c", "seamLabel": "neckline"},
                {"id": "y", "type": "line", "pieceId": "f", "seamLabel": "neckline",
                 "start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 5}},
                {"id": "z", "type": "line", "pieceId": "f", "seamLabel": "center_front",
                 "start": {"x": 0, "y": 5}, "end": {"x": 0, "y": 0}}]
    pieces = [{"id": "c", "name": "Collar", "elementIds": ["x"]},
              {"id": "f", "name": "Front Bodice", "elementIds": ["y", "z"]}]
    r = TestClient(app).post("/api/infer-attachments", json={"elements": elements, "pieces": pieces})
    assert r.status_code == 422


def test_a_band_longer_than_the_opening_keeps_its_overlap():
    """A waistband drawn longer than the waist is sewn length for length round
    it; the extra is left free at the end (the overlap), not squashed in."""
    from app.patterns.attachments import infer_attachments
    p = trousers()
    els = p["elements"]
    front = next(x for x in p["pieces"] if x["name"] == "Front Leg")
    back = next(x for x in p["pieces"] if x["name"] == "Back Leg")
    waist = sum(_edge_length(e) for pc in (front, back) for e in els if e["id"] in pc["elementIds"] and e.get("seamLabel") == "waist")
    band_len = 2 * waist + 12.0
    band = {"id": "wb", "name": "Waistband", "elementIds": ["b0", "b1", "b2", "b3"], "cutQty": 1, "onFold": False}
    corners = [(0, 0), (band_len, 0), (band_len, 8), (0, 8)]
    band_els = [{"id": f"b{i}", "type": "line", "pieceId": "wb", "isFold": False, "seamLabel": "waist" if i == 0 else "",
                 "start": {"x": corners[i][0], "y": corners[i][1]}, "end": {"x": corners[(i + 1) % 4][0], "y": corners[(i + 1) % 4][1]}}
                for i in range(4)]
    out = infer_attachments(els + band_els, p["pieces"] + [band], [])
    seams = [c for c in out["connections"] if c["from"]["pieceId"] == "wb"]
    assert [c["to"].get("side") for c in seams] == ["right", "right", "left", "left"]
    end = max(c["from"]["range"][1] for c in seams)
    assert math.isclose(end, 2 * waist / band_len, abs_tol=0.01)  # the last 12 cm are the overlap
