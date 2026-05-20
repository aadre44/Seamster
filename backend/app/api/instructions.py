import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.features import GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.instruction_generator import generate_instructions

logger = logging.getLogger(__name__)
router = APIRouter()


class InstructionsRequest(BaseModel):
    features: GarmentFeatures
    measurements: Measurements
    piece_names: list[str]


@router.post("/instructions")
async def instructions_endpoint(req: InstructionsRequest) -> dict:
    """Generate step-by-step sewing instructions for the given pattern."""
    if not req.piece_names:
        raise HTTPException(status_code=422, detail="piece_names must not be empty")

    try:
        result = await generate_instructions(req.features, req.measurements, req.piece_names)
    except ValueError as exc:
        logger.warning("Instruction generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error generating instructions")
        raise HTTPException(status_code=500, detail="Failed to generate instructions") from exc

    return result
