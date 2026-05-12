import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import Pattern
from app.schemas.pattern import (
    PatternCreate,
    PatternListItem,
    PatternResponse,
    PatternUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patterns", tags=["patterns"])

Db = Annotated[Session, Depends(get_db)]


def _extract_metadata(geometry: dict) -> dict:
    """Pull denormalized fields out of the geometry blob."""
    measurements = geometry.get("measurements", {})
    pieces = geometry.get("pieces", [])
    return {
        "piece_count": len(pieces),
        "waist_cm": measurements.get("waist"),
        "hip_cm": measurements.get("hip"),
    }


@router.post("", response_model=PatternResponse, status_code=201)
def create_pattern(body: PatternCreate, db: Db) -> PatternResponse:
    geo_dict = body.geometry.model_dump(by_alias=True)
    meta = _extract_metadata(geo_dict)
    pattern = Pattern(
        name=body.name,
        garment_type=body.garment_type,
        geometry=geo_dict,
        **meta,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return PatternResponse.model_validate(pattern)


@router.get("", response_model=list[PatternListItem])
def list_patterns(
    db: Db,
    garment_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PatternListItem]:
    q = db.query(Pattern)
    if garment_type:
        q = q.filter(Pattern.garment_type == garment_type)
    rows = q.order_by(Pattern.updated_at.desc()).offset(offset).limit(limit).all()
    return [PatternListItem.model_validate(r) for r in rows]


@router.get("/{pattern_id}", response_model=PatternResponse)
def get_pattern(pattern_id: str, db: Db) -> PatternResponse:
    pattern = db.get(Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return PatternResponse.model_validate(pattern)


@router.put("/{pattern_id}", response_model=PatternResponse)
def update_pattern(pattern_id: str, body: PatternUpdate, db: Db) -> PatternResponse:
    pattern = db.get(Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")

    if body.name is not None:
        pattern.name = body.name
    if body.garment_type is not None:
        pattern.garment_type = body.garment_type
    if body.geometry is not None:
        geo_dict = body.geometry.model_dump(by_alias=True)
        pattern.geometry = geo_dict
        meta = _extract_metadata(geo_dict)
        pattern.piece_count = meta["piece_count"]
        pattern.waist_cm = meta["waist_cm"]
        pattern.hip_cm = meta["hip_cm"]

    db.commit()
    db.refresh(pattern)
    return PatternResponse.model_validate(pattern)


@router.delete("/{pattern_id}", status_code=204)
def delete_pattern(pattern_id: str, db: Db) -> None:
    pattern = db.get(Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    db.delete(pattern)
    db.commit()
