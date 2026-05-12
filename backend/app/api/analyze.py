import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.models.features import SkirtFeatures
from app.vision.analyzer import analyze_skirt

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/analyze", response_model=SkirtFeatures)
async def analyze(
    front_image: UploadFile = File(..., description="Front-view photo of the skirt"),
    back_image: UploadFile | None = File(default=None, description="Optional back-view photo"),
) -> SkirtFeatures:
    for img in [front_image, back_image]:
        if img is None:
            continue
        if img.content_type not in ("image/jpeg", "image/png"):
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {img.content_type}. Use JPEG or PNG.")
        data = await img.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail=f"Image '{img.filename}' exceeds 10 MB limit.")
        img._data = data  # cache for downstream use

    front_bytes = front_image._data
    back_bytes = back_image._data if back_image else None

    try:
        features = await analyze_skirt(front_bytes, back_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Vision analysis failed")
        raise HTTPException(status_code=502, detail="Analysis service unavailable. Please try again.") from exc

    return features
