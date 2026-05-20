from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class GarmentType(str, Enum):
    SKIRT = "skirt"
    DRESS = "dress"
    TROUSERS = "trousers"
    PANTS = "pants"
    SHIRT = "shirt"
    BLOUSE = "blouse"
    JACKET = "jacket"
    BLAZER = "blazer"
    BODICE = "bodice"
    COAT = "coat"
    SHORTS = "shorts"


class WaistbandFeature(BaseModel):
    type: Literal["straight", "contoured", "elastic", "facing", "yoke"]
    width_cm_estimate: float = 3.0


class ClosureFeature(BaseModel):
    type: Literal["center_back_zip", "side_zip", "button_fly", "hook_and_eye", "none"]
    position: Literal["center_back", "left_side", "right_side", "center_front"]


class DartFeature(BaseModel):
    front: int = Field(ge=0, le=4)
    back: int = Field(ge=0, le=4)


class GarmentFeatures(BaseModel):
    """Generic feature set returned by vision analysis for any garment type."""
    garment_type: GarmentType
    silhouette: str
    length_category: str
    closure: ClosureFeature
    waistband: WaistbandFeature | None = None
    darts: DartFeature | None = None
    details: list[str] = Field(default_factory=list)
    sleeve_length: str | None = None   # "short" | "long" | "three_quarter" | "sleeveless"
    neckline: str | None = None         # "crew" | "v_neck" | "round" | "polo" | "boat" | "mandarin"
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


# Kept for backward compatibility with existing tests and the skirt pattern engine
class SkirtFeatures(BaseModel):
    garment_type: GarmentType = GarmentType.SKIRT
    silhouette: Literal["straight", "a_line", "pencil", "circle", "gathered", "pleated", "wrap"]
    length_category: Literal["mini", "above_knee", "knee", "midi", "maxi"]
    waistband: WaistbandFeature
    closure: ClosureFeature
    darts: DartFeature
    details: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str = ""
