import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.llm import LLMError
from app.models.features import GarmentType
from app.models.measurements import Measurements
from app.vision.refine import refine_pattern

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/refine")
async def refine(
    garment_type: GarmentType = Form(...),
    psnap: str = Form(..., description="The current .psnap document as a JSON string"),
    measurements: str = Form(..., description="Measurements as a JSON string"),
    front_image: UploadFile = File(..., description="Front-view photo of the garment"),
    back_image: UploadFile | None = File(default=None, description="Optional back-view photo"),
    notes: str = Form(default="", description="Analysis notes about the garment, for context"),
) -> dict:
    """Photo-driven refine pass: the vision LLM compares the drafted pieces to the
    photo and reshapes the ones that disagree. Returns the updated psnap plus a
    summary of which pieces changed."""
    for img in [front_image, back_image]:
        if img is None:
            continue
        if img.content_type not in ("image/jpeg", "image/png"):
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {img.content_type}. Use JPEG or PNG.")
        data = await img.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail=f"Image '{img.filename}' exceeds 10 MB limit.")
        img._data = data  # cache for downstream use

    try:
        psnap_dict = json.loads(psnap)
        if not isinstance(psnap_dict, dict):
            raise ValueError("psnap must be a JSON object")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Malformed psnap JSON: {exc}") from exc
    if not psnap_dict.get("pieces"):
        raise HTTPException(status_code=422, detail="The pattern has no pieces to refine.")
    try:
        m = Measurements.model_validate_json(measurements)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Malformed measurements JSON: {exc}") from exc

    try:
        updated, summary = await refine_pattern(
            psnap_dict, garment_type, m,
            front_bytes=front_image._data,
            back_bytes=back_image._data if back_image else None,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        logger.exception("Photo refine failed at the LLM provider")
        raise HTTPException(status_code=502, detail=f"Refine failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Photo refine failed")
        raise HTTPException(status_code=502, detail=f"Refine failed: {exc}") from exc

    return {"psnap": updated, "summary": summary}
