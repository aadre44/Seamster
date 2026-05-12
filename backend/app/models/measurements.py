from pydantic import BaseModel, Field


class Measurements(BaseModel):
    # Required
    waist_cm: float = Field(gt=40, lt=160, description="Natural waist circumference in cm")
    hip_cm: float = Field(gt=50, lt=180, description="Fullest hip circumference in cm")
    waist_to_hip_cm: float = Field(gt=10, lt=35, description="Vertical distance waist to hip in cm")
    length_cm: float = Field(gt=20, lt=150, description="Desired skirt length from waist to hem in cm")

    # Optional — sensible defaults applied by the pattern engine
    waistband_width_cm: float = Field(default=3.0, gt=0, lt=15)
    seam_allowance_cm: float = Field(default=1.5, gt=0, lt=5)
    hem_allowance_cm: float = Field(default=3.0, gt=0, lt=10)
