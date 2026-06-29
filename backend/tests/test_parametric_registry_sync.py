"""Drift guard: keep `_PARAMETRIC_DETAILS` in sync with what the builders emit.

The bug class this prevents: a parametric generator natively builds a piece for
some detail (e.g. a shirt's ``ribbed_collar``, a trouser's ``belt_loops``, a
dress's ``collar``), but that detail is missing from ``_PARAMETRIC_DETAILS``.
When that happens ``detect_unsupported_details`` does not filter it, so the LLM
fallback generates a *second*, duplicate piece for the same feature.

This is easy to introduce because several generators are shared
(shirt↔blouse, pants↔trousers) and the registry is maintained by hand. Rather
than discover each instance in production, this test probes every generator:
for any detail that makes the parametric builder produce an extra piece, the
detail MUST be registered for that garment type.
"""
from __future__ import annotations

import pytest

from app.models.features import (
    ClosureFeature,
    DartFeature,
    GarmentFeatures,
    GarmentType,
    WaistbandFeature,
)
from app.models.measurements import Measurements
from app.patterns.engine import (
    _generate_dress_pattern,
    _generate_jacket_pattern,
    _generate_shirt_pattern,
    _generate_skirt_pattern,
    _generate_trousers_pattern,
    _generate_vest_pattern,
)
from app.patterns.llm_fallback import _PARAMETRIC_DETAILS, _TECHNIQUES


def _measurements() -> Measurements:
    return Measurements(
        waist_cm=76.0, hip_cm=94.0, waist_to_hip_cm=21.0, length_cm=65.0,
        chest_cm=90.0, shoulder_width_cm=30.0, arm_length_cm=60.0,
        inseam_cm=76.0, rise_cm=28.0, seam_allowance_cm=1.5,
    )


# Each entry: garment type, the generator that serves it, and the base feature
# kwargs that produce a stable, minimal pattern (no detail pieces) to diff against.
_GENERATORS = {
    GarmentType.SKIRT: (
        _generate_skirt_pattern,
        dict(silhouette="straight", length_category="knee",
             closure=ClosureFeature(type="center_back_zip", position="center_back"),
             waistband=WaistbandFeature(type="straight", width_cm_estimate=3.0)),
    ),
    GarmentType.SHIRT: (
        _generate_shirt_pattern,
        dict(silhouette="regular", length_category="hip_length",
             closure=ClosureFeature(type="none", position="center_front"),
             sleeve_length="short", neckline="crew"),
    ),
    GarmentType.BLOUSE: (
        _generate_shirt_pattern,
        dict(silhouette="regular", length_category="hip_length",
             closure=ClosureFeature(type="none", position="center_front"),
             sleeve_length="short", neckline="crew"),
    ),
    GarmentType.TROUSERS: (
        _generate_trousers_pattern,
        dict(silhouette="regular", length_category="full_length",
             closure=ClosureFeature(type="button_fly", position="center_front"),
             waistband=WaistbandFeature(type="straight", width_cm_estimate=4.0)),
    ),
    GarmentType.PANTS: (
        _generate_trousers_pattern,
        dict(silhouette="regular", length_category="full_length",
             closure=ClosureFeature(type="button_fly", position="center_front"),
             waistband=WaistbandFeature(type="straight", width_cm_estimate=4.0)),
    ),
    GarmentType.DRESS: (
        _generate_dress_pattern,
        dict(silhouette="a_line", length_category="knee",
             closure=ClosureFeature(type="none", position="center_front"),
             sleeve_length="sleeveless", neckline="round"),
    ),
    GarmentType.JACKET: (
        _generate_jacket_pattern,
        dict(silhouette="regular", length_category="hip_length",
             closure=ClosureFeature(type="none", position="center_front"),
             sleeve_length="long"),
    ),
    GarmentType.BLAZER: (
        _generate_jacket_pattern,
        dict(silhouette="regular", length_category="hip_length",
             closure=ClosureFeature(type="none", position="center_front"),
             sleeve_length="long"),
    ),
    GarmentType.VEST: (
        _generate_vest_pattern,
        dict(silhouette="boxy", length_category="hip_length",
             closure=ClosureFeature(type="none", position="center_front"),
             neckline="notched_v"),
    ),
}

# Probe every detail that any garment registers as parametric (so a detail
# registered for one garment is checked against every generator that might also
# build it), plus a few builder triggers that aren't in any registry today.
_CANDIDATE_DETAILS = sorted(
    (set().union(*_PARAMETRIC_DETAILS.values()) - _TECHNIQUES)
    | {"belt", "sash", "tie_back", "belt_loops", "ribbed_collar"}
)


def _features(gtype: GarmentType, base_kwargs: dict, details: list[str]) -> GarmentFeatures:
    return GarmentFeatures(
        garment_type=gtype,
        darts=DartFeature(front=0, back=0),
        details=details,
        confidence=0.9,
        **base_kwargs,
    )


@pytest.mark.parametrize("gtype", list(_GENERATORS))
def test_builder_pieces_are_registered(gtype: GarmentType):
    """If a generator emits an extra piece for a detail, it must be registered."""
    generate, base_kwargs = _GENERATORS[gtype]
    m = _measurements()
    registered = _PARAMETRIC_DETAILS.get(gtype.value, set())

    base_count = len(generate(_features(gtype, base_kwargs, []), m)["pieces"])

    offenders: list[str] = []
    for detail in _CANDIDATE_DETAILS:
        out = generate(_features(gtype, base_kwargs, [detail]), m)
        if len(out["pieces"]) > base_count and detail not in registered:
            offenders.append(detail)

    assert not offenders, (
        f"{gtype.value}: the parametric builder emits a piece for "
        f"{offenders} but they are not in _PARAMETRIC_DETAILS['{gtype.value}'] — "
        f"the LLM fallback will generate duplicate pieces. Add them to the registry."
    )
