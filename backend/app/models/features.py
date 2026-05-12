from typing import Literal

from pydantic import BaseModel, Field


class WaistbandFeature(BaseModel):
    type: Literal["straight", "contoured", "elastic", "facing", "yoke"]
    width_cm_estimate: float = 3.0


class ClosureFeature(BaseModel):
    type: Literal["center_back_zip", "side_zip", "button_fly", "hook_and_eye", "none"]
    position: Literal["center_back", "left_side", "right_side", "center_front"]


class DartFeature(BaseModel):
    front: int = Field(ge=0, le=4)
    back: int = Field(ge=0, le=4)


class SkirtFeatures(BaseModel):
    silhouette: Literal["straight", "a_line", "pencil", "circle", "gathered", "pleated", "wrap"]
    length_category: Literal["mini", "above_knee", "knee", "midi", "maxi"]
    waistband: WaistbandFeature
    closure: ClosureFeature
    darts: DartFeature
    details: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str = ""
