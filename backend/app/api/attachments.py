"""POST /api/infer-attachments — seams and placements inferred for any pattern.

The Assembly view's "Re-infer" sends the current pieces (engine, AI or
hand-drawn) and gets back the label-based shell seams plus trim seams, pocket
placements and piece layers (app/patterns/attachments.py). The client keeps
the user's own seams and placements and replaces the inferred ones.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.patterns.attachments import infer_attachments
from app.patterns.engine import _compute_connections

logger = logging.getLogger(__name__)
router = APIRouter()


class InferAttachmentsRequest(BaseModel):
    # Loose dicts in .psnap shape; sizes capped (a real pattern has tens of pieces).
    elements: list[dict] = Field(max_length=5000)
    pieces: list[dict] = Field(max_length=300)


@router.post("/infer-attachments")
def infer(body: InferAttachmentsRequest) -> dict:
    try:
        connections = _compute_connections(body.elements, body.pieces)
        return infer_attachments(body.elements, body.pieces, connections)
    except (KeyError, TypeError, ValueError) as exc:
        logger.info("infer-attachments: malformed pattern (%s)", exc)
        raise HTTPException(status_code=422, detail="The pattern pieces could not be read.") from exc
