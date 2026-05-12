import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.models.features import SkirtFeatures
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern
from app.export.svg_renderer import render_svg
from app.export.pdf_tiler import tile_pdf

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateRequest(BaseModel):
    features: SkirtFeatures
    measurements: Measurements


@router.post("/generate")
async def generate(
    body: GenerateRequest,
    format: str = Query(default="pdf_tiled", pattern="^(pdf_tiled|pdf_single|svg)$"),
    paper: str = Query(default="a4", pattern="^(a4|letter)$"),
) -> Response:
    try:
        pieces = generate_pattern(body.features, body.measurements)
    except Exception as exc:
        logger.exception("Pattern generation failed")
        raise HTTPException(status_code=500, detail="Pattern generation failed. Check your measurements.") from exc

    try:
        svg_content = render_svg(pieces)
    except Exception as exc:
        logger.exception("SVG rendering failed")
        raise HTTPException(status_code=500, detail="Could not render pattern.") from exc

    if format == "svg":
        return Response(content=svg_content, media_type="image/svg+xml",
                        headers={"Content-Disposition": "attachment; filename=pattern.svg"})

    try:
        pdf_bytes = tile_pdf(svg_content, paper_size=paper, single_page=(format == "pdf_single"))
    except Exception as exc:
        logger.exception("PDF export failed")
        raise HTTPException(status_code=500, detail="Could not generate PDF.") from exc

    filename = f"pattern_{paper}{'_single' if format == 'pdf_single' else '_tiled'}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
