import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pydantic import BaseModel

from app.models.features import GarmentFeatures
from app.models.measurements import Measurements
from app.patterns.instruction_generator import PieceInfo, generate_instructions

logger = logging.getLogger(__name__)
router = APIRouter()


class InstructionsRequest(BaseModel):
    features: GarmentFeatures
    measurements: Measurements
    pieces: list[PieceInfo]


@router.post("/instructions")
async def instructions_endpoint(req: InstructionsRequest) -> dict:
    """Generate step-by-step sewing instructions for the given pattern."""
    if not req.pieces:
        raise HTTPException(status_code=422, detail="pieces must not be empty")

    try:
        result = await generate_instructions(req.features, req.measurements, req.pieces)
    except ValueError as exc:
        logger.warning("Instruction generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error generating instructions")
        raise HTTPException(status_code=500, detail="Failed to generate instructions") from exc

    return result
