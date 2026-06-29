"""Tests for the shared patch-pocket builder (bottom-shape geometry)."""
from app.patterns.geometry import CurveSegment, Point
from app.patterns.pockets import VALID_SHAPES, make_patch_pocket, make_welt_pocket

W, H, SA = 12.0, 14.0, 1.5


def _vertex_xy(outline):
    return [(round(v.x, 3), round(v.y, 3)) for v in outline]


def test_all_shapes_return_closed_outline():
    for shape in VALID_SHAPES:
        spec = make_patch_pocket("P", W, H, SA, shape=shape)
        assert len(spec.outline) >= 4
        # top edge is the straight opening at y=0 across the full width
        assert spec.outline[0].x == 0.0 and spec.outline[0].y == 0.0
        assert spec.outline[1].x == W and spec.outline[1].y == 0.0


def test_square_is_plain_rectangle():
    spec = make_patch_pocket("P", W, H, SA, shape="square")
    assert _vertex_xy(spec.outline) == [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]
    assert not any(isinstance(v, CurveSegment) for v in spec.outline)


def test_pointed_has_centre_apex_below_corners():
    spec = make_patch_pocket("P", W, H, SA, shape="pointed")
    apex = [v for v in spec.outline if abs(v.x - W / 2) < 1e-6 and v.y > H]
    assert apex, "pointed pocket must have a centre apex below the side corners"
    # the apex sits lower (larger y) than both bottom-side corners at y == H
    side_corner_ys = [v.y for v in spec.outline if abs(v.y - H) < 1e-6]
    assert apex[0].y > max(side_corner_ys)


def test_angled_chamfers_bottom_corners():
    spec = make_patch_pocket("P", W, H, SA, shape="angled")
    # six vertices, all straight; no corner sits exactly at (W, H) or (0, H)
    assert len(spec.outline) == 6
    assert not any(isinstance(v, CurveSegment) for v in spec.outline)
    corners = _vertex_xy(spec.outline)
    assert (W, H) not in corners and (0.0, H) not in corners


def test_rounded_and_curved_use_bezier_corners():
    for shape in ("rounded", "curved"):
        spec = make_patch_pocket("P", W, H, SA, shape=shape)
        assert any(isinstance(v, CurveSegment) for v in spec.outline), shape


def test_grain_line_runs_vertically_down_centre():
    spec = make_patch_pocket("P", W, H, SA, shape="pointed")
    assert spec.grain_start.x == spec.grain_end.x == W / 2
    assert spec.grain_start.y < spec.grain_end.y


def test_unknown_shape_falls_back_to_square():
    spec = make_patch_pocket("P", W, H, SA, shape="banana")
    assert _vertex_xy(spec.outline) == [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]


# ── Welt / besom pockets ──────────────────────────────────────────────────────

def test_welt_pocket_returns_strip_and_bag():
    strip, bag = make_welt_pocket(14.0, SA, cut_qty=2)
    assert strip.name == "Welt Strip"
    assert bag.name == "Welt Pocket Bag"
    assert strip.cut_qty == bag.cut_qty == 2


def test_welt_opening_width_is_parametric():
    narrow = make_welt_pocket(10.0, SA)[0]
    wide = make_welt_pocket(20.0, SA)[0]
    assert max(p.x for p in wide.outline) > max(p.x for p in narrow.outline)


def test_besom_strip_is_taller_than_single_welt():
    single = make_welt_pocket(14.0, SA, besom=False)[0]
    besom = make_welt_pocket(14.0, SA, besom=True)[0]
    assert max(p.y for p in besom.outline) > max(p.y for p in single.outline)


def test_welt_placement_note_is_recorded():
    strip = make_welt_pocket(14.0, SA, placement_note="on the lower front")[0]
    assert "lower front" in strip.notes
