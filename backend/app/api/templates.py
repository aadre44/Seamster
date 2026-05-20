"""REST endpoints for viewing and managing the learned pattern piece templates.

GET  /api/templates          — list all saved templates
GET  /api/templates/{id}     — get one template by id
DELETE /api/templates/{id}   — remove a bad or stale template

These endpoints let developers inspect what the LLM has learned, audit
formula quality, and clean up incorrect templates without touching the JSON
file directly.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.patterns.learned_pieces import PieceTemplate, get_store

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
