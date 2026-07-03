"""REST endpoints for viewing and managing the learned pattern piece templates.

GET  /api/templates          — list all saved templates
GET  /api/templates/{id}     — get one template by id
DELETE /api/templates/{id}   — remove a bad or stale template
POST /api/templates          — save a user-corrected piece outline as a template
                               (novel-piece tier 5 feedback loop: the editor's
                               "Save as template" on an AI-draft piece)

These endpoints let developers inspect what the LLM has learned, audit
formula quality, and clean up incorrect templates without touching the JSON
file directly.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.models.measurements import Measurements
from app.patterns.learned_pieces import (
    _MEASUREMENT_VARS,
    PieceTemplate,
    apply_template,
    get_store,
)
from app.patterns.novel_validation import ATTACHMENT_LABELS, validate_spec

router = APIRouter()


@router.get("/templates")
def list_templates() -> JSONResponse:
    """Return all learned templates sorted by times_used descending."""
    store = get_store()
    templates = sorted(store.all_templates, key=lambda t: t.times_used, reverse=True)
    return JSONResponse(content={
        "count": len(templates),
        "templates": [t.model_dump() for t in templates],
    })


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> JSONResponse:
    store = get_store()
    for t in store.all_templates:
        if t.id == template_id:
            return JSONResponse(content=t.model_dump())
    raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> JSONResponse:
    """Remove a template by id. The next request for its detail will call the LLM again."""
    store = get_store()
    removed = store.remove(template_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return JSONResponse(content={"deleted": template_id})


# ── Save a user-corrected outline as a template ───────────────────────────────

class TemplatePointIn(BaseModel):
    """One outline vertex in absolute editor cm; cp* describe the bezier INTO
    this vertex from the previous one (matching the custom-geometry contract)."""
    x: float
    y: float
    cp1x: float | None = None
    cp1y: float | None = None
    cp2x: float | None = None
    cp2y: float | None = None


class SaveTemplateRequest(BaseModel):
    trigger_detail: str = Field(min_length=1)
    garment_type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    cut_qty: int = Field(default=1, ge=1, le=8)
    on_fold: bool = False
    outline: list[TemplatePointIn] = Field(min_length=3, max_length=24)
    # The measurement the shape scales with, and its value in THIS pattern (cm):
    # each coordinate is stored as `reference * (coord / reference_value)` so the
    # corrected shape re-scales for any future body size.
    reference: str = "waist_cm"
    reference_value: float = Field(gt=0)
    attachment_label: str | None = None
    attachment_edges: list[int] | None = None


@router.post("/templates")
def save_template(req: SaveTemplateRequest) -> JSONResponse:
    """Persist a user-corrected piece outline as a parametric custom template.

    Replaces any existing template for the same detail + garment type (same id),
    so the corrected shape — not the LLM's original guess — is used next time."""
    if req.reference not in _MEASUREMENT_VARS:
        raise HTTPException(
            status_code=422,
            detail=f"reference must be one of {sorted(_MEASUREMENT_VARS)}",
        )
    if req.attachment_label is not None and req.attachment_label not in ATTACHMENT_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"attachment_label must be one of {list(ATTACHMENT_LABELS)} or null",
        )

    def formula(v: float) -> str:
        return f"{req.reference} * {v / req.reference_value:.5f}"

    points: list[dict] = []
    for pt in req.outline:
        entry: dict = {"x": formula(pt.x), "y": formula(pt.y)}
        if None not in (pt.cp1x, pt.cp1y, pt.cp2x, pt.cp2y):
            entry.update(
                cp1x=formula(pt.cp1x), cp1y=formula(pt.cp1y),
                cp2x=formula(pt.cp2x), cp2y=formula(pt.cp2y),
            )
        points.append(entry)

    xs = [p.x for p in req.outline]
    ys = [p.y for p in req.outline]
    template = PieceTemplate(
        id=f"{req.trigger_detail}-{req.garment_type}-v1",
        trigger_detail=req.trigger_detail,
        garment_types=[req.garment_type],
        name=req.name,
        description=req.description or f"user-corrected {req.name}",
        geometry="custom",
        length_formula=formula(max(ys) - min(ys) or 1.0),
        width_formula=formula(max(xs) - min(xs) or 1.0),
        cut_qty=req.cut_qty,
        on_fold=req.on_fold,
        points=points,
        attachment_label=req.attachment_label,
        attachment_edges=req.attachment_edges,
        created_at=datetime.now(timezone.utc).isoformat(),
        times_used=0,
    )

    # Sanity: the template must build and validate for a typical body before we
    # persist it — a broken save must not poison future generations.
    probe = Measurements(waist_cm=76, hip_cm=94, waist_to_hip_cm=21, length_cm=65)
    try:
        spec = apply_template(template, probe)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Outline cannot build: {exc}") from exc
    problems = validate_spec(spec, probe)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))

    get_store().add(template)
    return JSONResponse(content={"id": template.id, "points": len(points)})
