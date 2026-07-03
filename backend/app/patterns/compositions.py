"""Compose garments that have no dedicated block from existing parametric builders.

Novel-piece tier 4: instead of returning an empty placeholder for a garment type
without an engine, decompose it into components the engine already drafts well.

Resolution order (compose_pattern):
  1. STATIC_PLANS — a hand-written composition for known near-miss types
     (shorts → trousers, coat → jacket, tunic → shirt, romper/jumpsuit →
     shirt top + trouser bottom joined at a waist seam). No LLM involved.
  2. LLM planner — for types with no static plan, ask the LLM for a plan in the
     same constrained schema, validate it (builder names, override keys, join
     rules), re-prompt once with the validation errors, then give up.
  3. None — the caller falls back to the measurements-only placeholder.

Plans reference *builders* (existing per-garment generators), so all drafting
math stays in the trusted parametric blocks; composition only rewrites feature
routing, offsets the component layouts side by side, and relabels the joined
edges (previous component's ``hem`` + next component's ``waist`` → the join
label) so the connection pass sews the components together like a dress bodice
joins its skirt.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field

from app.llm import LLMError, complete_with_retry, get_provider
from app.models.features import ClosureFeature, GarmentFeatures, GarmentType
from app.models.measurements import Measurements

logger = logging.getLogger(__name__)

# Builders the planner may reference → the GarmentType routed to that generator.
_BUILDERS: dict[str, GarmentType] = {
    "skirt":    GarmentType.SKIRT,
    "shirt":    GarmentType.SHIRT,
    "trousers": GarmentType.TROUSERS,
    "dress":    GarmentType.DRESS,
    "jacket":   GarmentType.JACKET,
    "vest":     GarmentType.VEST,
    "bodice":   GarmentType.BODICE,
}

# Feature fields a component may override, and the closure types it may set.
_ALLOWED_OVERRIDE_KEYS = ("silhouette", "length_category", "sleeve_length", "neckline", "closure")
_ALLOWED_CLOSURES = (
    "none", "side_zip", "center_back_zip", "center_front_zip", "button_front", "button_fly",
)
# The only join implemented: sew this component's waist to the previous one's hem.
_JOIN_LABEL = "waist_seam"


@dataclass(frozen=True)
class ComponentSpec:
    builder: str
    overrides: dict = field(default_factory=dict)   # always applied
    defaults: dict = field(default_factory=dict)    # applied only when the feature is unset
    value_map: dict = field(default_factory=dict)   # {field: {detected_value: replacement}}
    join: str | None = None                         # _JOIN_LABEL on non-first components


@dataclass(frozen=True)
class CompositionPlan:
    components: tuple[ComponentSpec, ...]


STATIC_PLANS: dict[str, CompositionPlan] = {
    # Shorts are trousers whose length vocabulary the trouser block already maps
    # (micro/short → shorts, mid_thigh/knee → bermuda); only default the length.
    "shorts": CompositionPlan((
        ComponentSpec("trousers", defaults={"length_category": "shorts"}),
    )),
    # A coat is a longer jacket; translate coat-only lengths onto the jacket vocab.
    "coat": CompositionPlan((
        ComponentSpec(
            "jacket",
            defaults={"length_category": "knee"},
            value_map={"length_category": {"midi": "knee", "maxi": "knee"}},
        ),
    )),
    # A tunic is a long shirt — the shirt block reads length from measurements.
    "tunic": CompositionPlan((
        ComponentSpec("shirt", defaults={"silhouette": "longline"}),
    )),
    "romper": CompositionPlan((
        ComponentSpec("shirt"),
        ComponentSpec(
            "trousers",
            overrides={"length_category": "shorts", "closure": "none"},
            join=_JOIN_LABEL,
        ),
    )),
    "jumpsuit": CompositionPlan((
        ComponentSpec("shirt"),
        ComponentSpec(
            "trousers",
            overrides={"closure": "none"},
            defaults={"length_category": "full_length"},
            join=_JOIN_LABEL,
        ),
    )),
}


# ── Public API ────────────────────────────────────────────────────────────────

def compose_pattern(
    features: GarmentFeatures,
    measurements: Measurements,
    shape_mode: str = "modifiers",
) -> dict | None:
    """Return a composed .psnap dict for a garment type with no dedicated block,
    or None when no valid composition can be found (caller shows the placeholder)."""
    plan = STATIC_PLANS.get(features.garment_type.value)
    if plan is None:
        plan = _plan_from_llm(features)
    if plan is None:
        return None
    try:
        return _execute_plan(plan, features, measurements, shape_mode)
    except Exception:
        logger.exception(
            "Composition failed for garment_type='%s'", features.garment_type.value
        )
        return None


# ── Plan execution ────────────────────────────────────────────────────────────

def _component_features(comp: ComponentSpec, features: GarmentFeatures) -> GarmentFeatures:
    """Re-route the detected features at one component's builder."""
    update: dict = {"garment_type": _BUILDERS[comp.builder]}

    for key, mapping in comp.value_map.items():
        current = getattr(features, key, None)
        if current in mapping:
            update[key] = mapping[current]
    for key, value in comp.defaults.items():
        if not getattr(features, key, None) and key not in update:
            update[key] = value
    for key, value in comp.overrides.items():
        update[key] = value

    closure = update.pop("closure", None)
    if closure in _ALLOWED_CLOSURES:
        update["closure"] = ClosureFeature(type=closure, position="center_front")
    return features.model_copy(update=update)


def _shift_elements(elements: list[dict], dx: float) -> None:
    for elem in elements:
        for key in ("start", "end", "cp1", "cp2"):
            pt = elem.get(key)
            if pt is not None:
                pt["x"] = pt["x"] + dx


def _max_x(elements: list[dict]) -> float:
    xs = [
        pt["x"]
        for elem in elements
        for key in ("start", "end", "cp1", "cp2")
        if (pt := elem.get(key)) is not None
    ]
    return max(xs) if xs else 0.0


def _execute_plan(
    plan: CompositionPlan,
    features: GarmentFeatures,
    measurements: Measurements,
    shape_mode: str,
) -> dict:
    # Deferred import: engine imports compose_pattern for its unsupported-type
    # branch, so importing engine at module load would be circular.
    from app.patterns import engine

    merged_elements: list[dict] = []
    merged_pieces: list[dict] = []
    merged_measurements: dict = {}
    prev_elements: list[dict] | None = None
    cursor_x = 0.0
    gap = 5.0

    for comp in plan.components:
        comp_psnap = engine._generate_base(
            _component_features(comp, features), measurements, shape_mode
        )
        if comp_psnap is None:  # unreachable while _BUILDERS maps to supported types
            raise ValueError(f"builder '{comp.builder}' has no generator")

        elements = copy.deepcopy(comp_psnap["elements"])
        pieces = copy.deepcopy(comp_psnap["pieces"])

        # Join: the previous component's hem and this component's waist become one
        # seam label, exactly like the dress builder's bodice/skirt waist_seam.
        if comp.join and prev_elements is not None:
            for elem in prev_elements:
                if elem.get("seamLabel") == "hem":
                    elem["seamLabel"] = comp.join
            for elem in elements:
                if elem.get("seamLabel") == "waist":
                    elem["seamLabel"] = comp.join

        _shift_elements(elements, cursor_x)
        cursor_x = _max_x(elements) + gap

        merged_elements.extend(elements)
        merged_pieces.extend(pieces)
        merged_measurements.update(comp_psnap.get("measurements", {}))
        prev_elements = elements

    return {
        "version": 1,
        "elements": merged_elements,
        "pieces": merged_pieces,
        "measurements": merged_measurements,
        "connections": engine._compute_connections(merged_elements, merged_pieces),
    }


# ── LLM planner ───────────────────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """\
You are a garment construction planner for a parametric sewing-pattern engine.
The engine has trusted builders for: skirt, shirt, trousers, dress, jacket, vest, bodice.
Given a garment it has NO builder for, decompose it into 1-3 components of those builders.

Respond with ONLY a valid JSON object — no markdown fences, no commentary:
{
  "components": [
    {
      "builder": "<skirt | shirt | trousers | dress | jacket | vest | bodice>",
      "overrides": { "silhouette": "...", "length_category": "...",
                     "sleeve_length": "...", "neckline": "...", "closure": "..." },
      "join": "waist_seam" or null
    }
  ]
}

Rules:
- List components top-of-body first.
- join="waist_seam" sews that component's waist edge to the PREVIOUS component's hem
  (e.g. overalls = shirt [sleeveless] + trousers joined at waist_seam). The first
  component's join must be null.
- overrides is optional; include only what you need, using vocabulary the builders
  understand (e.g. trousers length_category "shorts"/"capri", shirt silhouette
  "longline", closure "none" for a joined bottom).
- Prefer ONE component reshaped by overrides over multiple components when the
  garment is a variation of a single builder (culottes = wide_leg capri trousers).
"""


def _planner_user_prompt(features: GarmentFeatures, problems: list[str]) -> str:
    text = (
        f"Plan the composition for this garment:\n\n"
        f"  garment_type: {features.garment_type.value}\n"
        f"  silhouette: {features.silhouette}\n"
        f"  length_category: {features.length_category}\n"
        f"  sleeve_length: {features.sleeve_length}\n"
        f"  neckline: {features.neckline}\n"
        f"  details: {features.details}\n"
        f"  notes: {features.notes}\n"
    )
    if problems:
        text += (
            "\nYOUR PREVIOUS PLAN WAS REJECTED for these reasons:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nFix every problem and return the corrected JSON object.\n"
        )
    return text + "\nReturn only the JSON object."


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.MULTILINE)
    return re.sub(r"\n?```$", "", text.strip())


def _validate_plan(data: dict) -> tuple[CompositionPlan | None, list[str]]:
    errors: list[str] = []
    components = data.get("components")
    if not isinstance(components, list) or not 1 <= len(components) <= 3:
        return None, ["'components' must be an array of 1 to 3 component objects"]

    specs: list[ComponentSpec] = []
    for i, comp in enumerate(components):
        if not isinstance(comp, dict):
            errors.append(f"component {i} is not an object")
            continue
        builder = comp.get("builder")
        if builder not in _BUILDERS:
            errors.append(
                f"component {i}: unknown builder {builder!r} — must be one of {sorted(_BUILDERS)}"
            )
            continue
        overrides = comp.get("overrides") or {}
        if not isinstance(overrides, dict):
            errors.append(f"component {i}: 'overrides' must be an object")
            continue
        bad_keys = [k for k in overrides if k not in _ALLOWED_OVERRIDE_KEYS]
        if bad_keys:
            errors.append(
                f"component {i}: unsupported override keys {bad_keys} — "
                f"allowed: {list(_ALLOWED_OVERRIDE_KEYS)}"
            )
            continue
        if not all(isinstance(v, str) for v in overrides.values()):
            errors.append(f"component {i}: override values must be strings")
            continue
        join = comp.get("join")
        if join not in (None, _JOIN_LABEL):
            errors.append(f"component {i}: join must be \"{_JOIN_LABEL}\" or null")
            continue
        if join and i == 0:
            errors.append("the first component's join must be null")
            continue
        specs.append(ComponentSpec(builder, overrides=overrides, join=join))

    if errors:
        return None, errors
    return CompositionPlan(tuple(specs)), []


def _plan_from_llm(features: GarmentFeatures) -> CompositionPlan | None:
    """Ask the LLM for a composition plan; one repair re-prompt, then give up."""
    try:
        provider = get_provider()
    except ValueError:
        logger.warning("No LLM provider configured — skipping composition planner")
        return None

    problems: list[str] = []
    for attempt in range(2):
        try:
            response = complete_with_retry(
                provider,
                system=_PLANNER_SYSTEM_PROMPT,
                user_text=_planner_user_prompt(features, problems),
                max_tokens=600,
            )
        except (LLMError, ValueError):
            logger.exception(
                "Planner LLM call failed for '%s'", features.garment_type.value
            )
            return None

        try:
            data = json.loads(_strip_fences(response.text))
        except Exception:
            problems = ["the response was not a single valid JSON object"]
            continue

        plan, errors = _validate_plan(data)
        if plan is not None:
            logger.info(
                "Planner composed '%s' from %s",
                features.garment_type.value,
                [c.builder for c in plan.components],
            )
            return plan
        logger.info(
            "Planner attempt %d for '%s' rejected: %s",
            attempt + 1, features.garment_type.value, "; ".join(errors),
        )
        problems = errors

    return None
