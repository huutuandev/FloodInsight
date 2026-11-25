from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from .gateway import Code, LocationRow, Version


class RiskGeneration(BaseModel):
    location: Code | None = None
    issued_at: AwareDatetime | None = None


class FloodPredictionRequest(BaseModel):
    location: Code
    issued_at: AwareDatetime | None = None
    version: Version | None = None


class FloodStudy(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    as_of: AwareDatetime
    cutoffs: tuple[AwareDatetime, AwareDatetime, AwareDatetime]
    locations: dict[str, list[Code]]
    surveillance_reference: str = Field(min_length=1, max_length=1000)


class FloodTrainingRequest(BaseModel):
    study: FloodStudy | None = None


class Assessment(BaseModel, extra="allow"):
    id: int
    location: Code
    issued_at: datetime
    valid_until: datetime
    created_at: datetime
    risk_category: Literal["Low", "Moderate", "High", "Very High", "Insufficient Data"]
    risk_index: float | None = Field(ge=0, le=100)
    flood_probability: None
    forecast_horizon_hours: int
    assessment_status: str
    method_version: str
    weight_coverage: float
    missing_features: list[str]


class PointAssessment(BaseModel):
    point: LocationRow
    assessment: Assessment | None
    is_current: bool


class Prediction(BaseModel, extra="allow"):
    location: Code
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    flood_probability: float | None = Field(ge=0, le=1)
    status: str
    risk_classification: str
    model_version: str | None
    model_validation_status: str
    input_quality: dict


class Readiness(BaseModel):
    status: str
    inventory: dict[str, int]
    blocking_inventory: list[str]


class TrainingResult(BaseModel, extra="allow"):
    status: str


class Metrics(BaseModel, extra="allow"):
    status: str
    version: str | None
    evaluation: dict | None
    readiness: Readiness


class Coverage(BaseModel, extra="allow"):
    counts: dict[str, int]
    label_counts: dict[str, int]
    weather_daily: list[dict]
    weather_provider_grids: list[dict]
    terrain: list[dict]
    hydrology: list[dict]
    events: list[dict]
