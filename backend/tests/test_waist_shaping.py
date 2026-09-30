"""Sewn waists: darts must not double-count the hip→waist reduction.

A waist edge drawn at the waist quarter that ALSO carries darts sews up far too
small (a 74 cm body got a ~48 cm skirt waist). The invariant checked here is the
one that matters for wearability: waist edge minus dart intake = target waist,
and a skirt sewn to a bodice matches the bodice waist on each side.
"""
import math

import pytest

from app.models.measurements import Measurements
from app.patterns.dresses import build_dress_block
from app.patterns.skirts import build_skirt_block, split_waist_reduction


def _m(**overrides) -> Measurements:
    d = dict(waist_cm=74.0, hip_cm=98.0, waist_to_hip_cm=20.0, length_cm=60.0,
             chest_cm=92.0, shoulder_width_cm=39.0, arm_length_cm=58.0)
    d.update(overrides)
    return Measurements(**d)


def _waist_edge(spec) -> float:
    return max(p.x for p in spec.outline if math.isclose(p.y, 0.0, abs_tol=1e-6))


def _sewn(spec) -> float:
    return _waist_edge(spec) - sum(d.width for d in spec.darts)


def test_split_takes_the_reduction_exactly_once():
    dart, side = split_waist_reduction(6.5, 0.4, 3.0)
    assert math.isclose(dart + side, 6.5)
    assert math.isclose(dart, 2.6)
    assert split_waist_reduction(10.0, 0.6, 5.0) == (5.0, 5.0)  # capped dart
    assert split_waist_reduction(-1.0, 0.4, 3.0) == (0.0, 0.0)


@pytest.mark.parametrize("fit", ["straight", "pencil", "a_line", "trumpet", "mermaid"])
@pytest.mark.parametrize("waist,hip", [(64.0, 90.0), (74.0, 98.0), (92.0, 110.0)])
def test_darted_skirt_sews_to_the_waist(fit, waist, hip):
    block = build_skirt_block(_m(waist_cm=waist, hip_cm=hip), fit_style=fit)
    front, back = block["front"], block["back"]
    assert front.darts and back.darts
    total = 2 * _sewn(front) + 2 * _sewn(back)  # front on fold (×2), back cut 2
    assert math.isclose(total, waist, abs_tol=0.01)


@pytest.mark.parametrize("fit", ["flared", "circle"])
def test_dartless_skirt_waist_edge_is_the_waist(fit):
    block = build_skirt_block(_m(), fit_style=fit)
    assert not block["front"].darts and not block["back"].darts
    assert math.isclose(2 * _waist_edge(block["front"]) + 2 * _waist_edge(block["back"]), 74.0, abs_tol=0.01)


@pytest.mark.parametrize("fit", ["shift", "sheath", "a_line", "fit_and_flare", "bodycon", "empire"])
def test_dress_skirt_waist_matches_bodice_waist(fit):
    block = build_dress_block(_m(length_cm=100.0), fit_style=fit)

    def bodice_waist(spec) -> float:
        bottom = max(p.y for p in spec.outline)
        edge = max(p.x for p in spec.outline if math.isclose(p.y, bottom, abs_tol=1e-6))
        return edge - sum(d.width for d in spec.darts)

    assert math.isclose(_sewn(block["front_skirt"]), bodice_waist(block["front_bodice"]), abs_tol=0.01)
    assert math.isclose(_sewn(block["back_skirt"]), bodice_waist(block["back_bodice"]), abs_tol=0.01)


@pytest.mark.parametrize("length", [70.0, 80.0])
def test_hip_length_shirt_hem_clears_the_hips(length):
    """A shirt long enough to cover the hips must be at least hip-sized at the hem."""
    from app.patterns.shirts import build_shirt_block
    block = build_shirt_block(_m(length_cm=length))
    halves = []
    for key in ("front_bodice", "back_bodice"):
        spec = block[key]
        bottom = max(p.y for p in spec.outline)
        halves.append(max(p.x for p in spec.outline if abs(p.y - bottom) < 1e-6))
    # Front and back are each cut on the fold: the hem is 2 × (front half + back half).
    assert 2 * sum(halves) >= 98.0 + 2.0


def test_waist_length_shirt_hem_stays_at_the_waist():
    from app.patterns.shirts import build_shirt_block
    block = build_shirt_block(_m(length_cm=40.0))
    front = block["front_bodice"]
    bottom = max(p.y for p in front.outline)
    assert max(p.x for p in front.outline if abs(p.y - bottom) < 1e-6) < (98.0 + 4.0) / 4


@pytest.mark.parametrize("fit", ["shift", "a_line", "fit_and_flare", "empire"])
@pytest.mark.parametrize("category,waist_to_hem", [("mini", 42.0), ("knee", 60.0), ("midi", 85.0)])
def test_dress_skirt_reaches_the_length_category(fit, category, waist_to_hem):
    """Dress lengths are waist-to-hem: a knee dress's skirt must reach the knee,
    not stop at the hip (which flared the hem out like a peplum)."""
    block = build_dress_block(_m(), fit_style=fit, length_category=category)
    skirt_len = max(p.y for p in block["front_skirt"].outline)
    empire_drop = 10.0 if fit == "empire" else 0.0
    assert math.isclose(skirt_len, waist_to_hem + empire_drop, abs_tol=0.5)


def test_button_placket_widens_the_front_beyond_the_cf():
    """The button extension lies past the CF line: the front grows by the
    placket width (it used to shrink by it, making the shirt 6 cm too small)."""
    from app.patterns.geometry import CurveSegment
    from app.patterns.shirts import _PLACKET_WIDTH, build_shirt_block

    def xs(spec):
        return [p.x for p in spec.outline]

    plain = build_shirt_block(_m(length_cm=70.0))["front_bodice"]
    placket = build_shirt_block(_m(length_cm=70.0), has_placket=True)["front_bodice"]
    assert min(xs(placket)) == 0.0
    assert math.isclose(max(xs(placket)), max(xs(plain)) + _PLACKET_WIDTH)
    # the armhole curve moved with the rest of the front
    curves = [(a, b) for a, b in zip(plain.outline, placket.outline) if isinstance(a, CurveSegment)]
    assert curves and all(math.isclose(b.cp1.x, a.cp1.x + _PLACKET_WIDTH) for a, b in curves if a.x != 0.0)


def test_shirt_collar_matches_the_neckline_it_is_sewn_to():
    """Collar length = the neckline measured along its curves (both halves,
    front and back) + seam allowances — not the neckline widths, which left a
    shirt collar ~10–25 % short (fixList #23)."""
    from app.patterns.shirts import _labelled_length, build_shirt_block
    for placket in (False, True):
        m = _m(length_cm=70.0)
        block = build_shirt_block(m, has_collar=True, has_placket=placket)
        neck = 2 * (_labelled_length(block["front_bodice"], "neckline") + _labelled_length(block["back_bodice"], "neckline"))
        collar_len = max(p.x for p in block["collar"].outline)
        assert math.isclose(collar_len, neck + 2 * m.seam_allowance_cm, abs_tol=0.05)


def test_button_front_marks_its_centre_front_line():
    """Where the buttons sit and the fronts meet: _PLACKET_WIDTH in from the edge."""
    from app.patterns.shirts import _PLACKET_WIDTH, build_shirt_block
    front = build_shirt_block(_m(length_cm=70.0), has_placket=True)["front_bodice"]
    (mark,) = [m for m in front.marks if m.label == "center_front_line"]
    assert all(math.isclose(p.x, _PLACKET_WIDTH) for p in mark.points)
    assert not [m for m in build_shirt_block(_m(length_cm=70.0))["front_bodice"].marks if m.label == "center_front_line"]
