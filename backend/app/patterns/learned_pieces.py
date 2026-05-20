"""Persisted template store for LLM-generated pattern pieces.

When the LLM generates a novel piece for an unseen garment detail, its
parametric description (formulas, not absolute coordinates) is saved here.
Subsequent requests for the same detail use the template directly instead
of calling the LLM again, making the parametric engine progressively richer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models.measurements import Measurements
from app.patterns.geometry import Point
from app.patterns.skirts import PieceSpec

TEMPLATES_PATH = Path(__file__).parent / "templates" / "learned.json"

# All field names that are valid in formula expressions
_MEASUREMENT_VARS: frozenset[str] = frozenset({
    "waist_cm", "hip_cm", "waist_to_hip_cm", "length_cm",
    "waistband_width_cm", "seam_allowance_cm", "hem_allowance_cm",
    "chest_cm", "shoulder_width_cm", "arm_length_cm",
    "inseam_cm", "rise_cm",
})

# Sensible fallbacks for optional measurements that may be None
_MEASUREMENT_DEFAULTS: dict[str, float] = {
    "chest_cm": 90.0,
    "shoulder_width_cm": 38.0,
    "arm_length_cm": 60.0,
    "inseam_cm": 76.0,
    "rise_cm": 28.0,
}


class PieceTemplate(BaseModel):
    """Parametric description of a novel piece learned from LLM output.

    Dimensions are stored as formula strings (arithmetic expressions using
    measurement variable names) so the template can be re-evaluated for any
    body size. The geometry field controls how the formula values are
    assembled into a PieceSpec outline.
    """
    id: str                          # e.g. "spaghetti_straps-shirt-v1"
    trigger_detail: str              # feature detail string that activates this piece
    garment_types: list[str]         # garment types this applies to
    name: str                        # piece name shown on the pattern
    description: str
    geometry: str                    # "rectangle" (future: "trapezoid", "custom")
    length_formula: str              # e.g. "shoulder_width_cm * 1.8"
    width_formula: str               # e.g. "1.5"
    cut_qty: int = 2
    on_fold: bool = False
    seam_allowance_formula: str = "seam_allowance_cm"
    grain_direction: str = "length"  # "length" (along Y) | "width" (along X)
    created_at: str = ""
    times_used: int = 0


class TemplateStore:
    """JSON-backed store for PieceTemplates.

    Loads once from disk on first access. Writes back on every add or
    times_used update. Thread-safety is not required for single-process use.
    """

    def __init__(self, path: Path = TEMPLATES_PATH) -> None:
        self._path = path
        self._templates: list[PieceTemplate] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._templates = [PieceTemplate(**t) for t in raw.get("pieces", [])]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"pieces": [t.model_dump() for t in self._templates]}
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def find(self, detail: str, garment_type: str) -> PieceTemplate | None:
        """Return the first template matching the detail + garment type, or None."""
        for t in self._templates:
            if t.trigger_detail == detail and garment_type in t.garment_types:
                return t
        return None

    def add(self, template: PieceTemplate) -> None:
        """Insert or replace a template by id, then persist."""
        self._templates = [t for t in self._templates if t.id != template.id]
        self._templates.append(template)
        self._save()

    def remove(self, template_id: str) -> bool:
        """Remove a template by id. Returns True if found and removed."""
        before = len(self._templates)
        self._templates = [t for t in self._templates if t.id != template_id]
        if len(self._templates) < before:
            self._save()
            return True
        return False

    def record_use(self, template_id: str) -> None:
        """Increment the times_used counter for a template, then persist."""
        for t in self._templates:
            if t.id == template_id:
                t.times_used += 1
        self._save()

    @property
    def all_templates(self) -> list[PieceTemplate]:
        return list(self._templates)


# ── Formula evaluation ────────────────────────────────────────────────────────

def _eval_formula(formula: str, ns: dict[str, Any]) -> float:
    """Safely evaluate an arithmetic formula string against a variable namespace.

    Only measurement variable names, the functions max/min, numeric literals,
    and arithmetic operators (+, -, *, /, parentheses) are permitted.
    Raises ValueError for any formula that doesn't pass validation.
    """
    # Validate: replace known identifiers, then check only safe characters remain
    test = formula
    allowed_names = _MEASUREMENT_VARS | {"max", "min"}
    for name in sorted(allowed_names, key=len, reverse=True):
        test = test.replace(name, "1")
    if not re.match(r"^[\d\s\.\+\-\*\/\(\)\,]+$", test):
        raise ValueError(f"Unsafe formula expression: {formula!r}")

    safe_ns = {**ns, "max": max, "min": min, "__builtins__": {}}
    return float(eval(formula, safe_ns))  # noqa: S307 — validated above


def _measurement_namespace(m: Measurements) -> dict[str, float]:
    ns: dict[str, float] = {}
    for field in _MEASUREMENT_VARS:
        val = getattr(m, field, None)
        ns[field] = val if val is not None else _MEASUREMENT_DEFAULTS.get(field, 0.0)
    return ns


# ── Template → PieceSpec ──────────────────────────────────────────────────────

def apply_template(template: PieceTemplate, m: Measurements) -> PieceSpec:
    """Evaluate a PieceTemplate's formulas against concrete measurements → PieceSpec."""
    ns = _measurement_namespace(m)
    length = _eval_formula(template.length_formula, ns)
    width = _eval_formula(template.width_formula, ns)
    seam = _eval_formula(template.seam_allowance_formula, ns)

    if template.grain_direction == "length":
        # Piece stands vertically: width along X, length along Y
        outline = [
            Point(0.0, 0.0),
            Point(width, 0.0),
            Point(width, length),
            Point(0.0, length),
        ]
        grain_start = Point(width / 2, length * 0.1)
        grain_end = Point(width / 2, length * 0.9)
    else:
        # Piece lies horizontally: length along X, width along Y
        outline = [
            Point(0.0, 0.0),
            Point(length, 0.0),
            Point(length, width),
            Point(0.0, width),
        ]
        grain_start = Point(length * 0.1, width / 2)
        grain_end = Point(length * 0.9, width / 2)

    return PieceSpec(
        name=template.name,
        outline=outline,
        darts=[],
        grain_start=grain_start,
        grain_end=grain_end,
        cut_qty=template.cut_qty,
        on_fold=template.on_fold,
        seam_allowance=seam,
    )


# ── Module-level singleton ────────────────────────────────────────────────────

_store: TemplateStore | None = None


def get_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store
