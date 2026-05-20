import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.export.pdf_tiler import tile_pdf

logger = logging.getLogger(__name__)
router = APIRouter()


class ExportPDFRequest(BaseModel):
    elements: list[dict[str, Any]] = []
    pieces: list[dict[str, Any]] = []
    paper_size: str = "a4"
    single_page: bool = False
    instructions: dict[str, Any] | None = None


@router.post("/export/pdf")
def export_pdf(req: ExportPDFRequest):
    pdf_bytes = tile_pdf(
        elements=req.elements,
        pieces=req.pieces,
        paper_size=req.paper_size,
        single_page=req.single_page,
        instructions=req.instructions,
    )
    filename = "pattern-single.pdf" if req.single_page else f"pattern-{req.paper_size}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
