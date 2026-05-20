import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models.features import GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.engine import generate_pattern

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateRequest(BaseModel):
    features: GarmentFeatures
    measurements: Measurements


@router.post("/generate")
def generate(body: GenerateRequest) -> JSONResponse:
    """Generate a .psnap pattern from confirmed features + measurements.

    Returns the .psnap document as JSON so the frontend can load it directly
    into the editor via LOAD_STATE dispatch.
    """
    try:
        psnap = generate_pattern(body.features, body.measurements)
    except Exception as exc:
        logger.exception("Pattern generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Pattern generation failed: {exc}",
        ) from exc

    return JSONResponse(content=psnap)
