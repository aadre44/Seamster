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
