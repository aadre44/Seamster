from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# .psnap geometry schemas
# ---------------------------------------------------------------------------

class ElementSchema(BaseModel):
    type: str  # "line" | "curve"
    from_point: list[float] = Field(alias="from")
    to: list[float]
    cp1: list[float] | None = None  # bezier control point 1 (curve only)
    cp2: list[float] | None = None  # bezier control point 2 (curve only)
    formula: str | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_curve_fields(self) -> "ElementSchema":
        if self.type == "curve" and (self.cp1 is None or self.cp2 is None):
            raise ValueError("Curve elements must include cp1 and cp2")
        return self


class GrainLineSchema(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class NotchSchema(BaseModel):
    element_index: int
    t: float = Field(ge=0.0, le=1.0)  # position along element (0 = start, 1 = end)


class PieceSchema(BaseModel):
    id: str
    name: str
    cut_qty: int = Field(default=1, ge=1)
    on_fold: bool = False
    elements: list[ElementSchema] = []
    seam_allowance: float = Field(default=1.5, ge=0.0)
    grain_lines: list[GrainLineSchema] = []
    notches: list[NotchSchema] = []


class GeometrySchema(BaseModel):
    version: int = 1
    measurements: dict[str, float] = {}
    pieces: list[PieceSchema] = []


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------

class PatternCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    garment_type: str | None = None
    geometry: GeometrySchema


class PatternUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    garment_type: str | None = None
    geometry: GeometrySchema | None = None


class PatternListItem(BaseModel):
    id: str
    name: str
    garment_type: str | None
    piece_count: int
    waist_cm: float | None
    hip_cm: float | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatternResponse(PatternListItem):
    geometry: dict[str, Any]  # raw .psnap document; no re-validation overhead on read
