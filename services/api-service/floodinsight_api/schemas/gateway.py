from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, Field, model_validator

T = TypeVar("T")
Code = Annotated[str, Field(min_length=1, max_length=100)]
Version = Annotated[str, Field(pattern="^[0-9a-f]{32}$")]
Period = Literal["daily", "weekly", "monthly"]
Pattern = Literal[
    "rainfall_daily", "rainfall_weekly", "rainfall_monthly", "rainfall_vs_humidity",
    "rainfall_vs_temperature", "rainfall_histogram", "monthly_trend", "monthly_seasonality",
    "correlation", "descriptive_statistics",
]


class Meta(BaseModel):
    request_id: str
    kind: str | None = None
    limit: int | None = None
    offset: int | None = None
    has_more: bool | None = None


class Success(BaseModel, Generic[T]):
    data: T
    meta: Meta


class ErrorDetail(BaseModel):
    code: str
    message: str
    service: str | None = None
    details: list[dict[str, str]] | None = None


class Failure(BaseModel):
    error: ErrorDetail
    meta: Meta


class Page(BaseModel):
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0, le=1_000_000)


class Locations(Page):
    location: Code | None = None


class DateRange(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates(self):
        if self.start_date < date(1900, 1, 1) or self.end_date > date(2200, 12, 30):
            raise ValueError("Date outside the supported calendar")
        if not 0 <= (self.end_date - self.start_date).days < 3660:
            raise ValueError("Specify an inclusive date range of at most 3,660 days")
        return self


class WeatherQuery(DateRange, Locations):
    source: Code | None = None


class AnalysisScope(DateRange):
    location: Code
    source: Code = "open-meteo-archive-era5"


class AnalysisQuery(AnalysisScope):
    pattern: Pattern | None = None


class BatchRequest(DateRange):
    max_batches: int | None = Field(None, ge=1, le=120)


class BackfillRequest(BatchRequest):
    refresh_incomplete: bool = False


class ETLRequest(BatchRequest):
    reprocess: bool = False
    after_batch_id: int = Field(0, ge=0, le=9223372036854775807)


class ModelWindow(DateRange):
    location: Code | None = None


class ClusterTrain(ModelWindow):
    clusters: int = Field(3, ge=2, le=12)
    scan_k: bool = False


class ClusterRun(ModelWindow):
    version: Version | None = None


class ForecastTrain(ModelWindow):
    availability: Literal["recorded", "retrospective"] = "recorded"
    residual_on_climatology: bool = False
    simple_tree: bool = False


class Thresholds(BaseModel):
    light_mm: float = Field(0.1, gt=0, allow_inf_nan=False)
    moderate_mm: float = Field(10, gt=0, allow_inf_nan=False)
    heavy_mm: float = Field(25, gt=0, allow_inf_nan=False)


class ClassTrain(ForecastTrain):
    thresholds: Thresholds = Field(default_factory=Thresholds)
    class_weight: Literal["balanced_subsample", "balanced"] = "balanced_subsample"
    three_classes: bool = False


class NextDay(BaseModel):
    location: Code
    version: Version | None = None
    issued_at: AwareDatetime | None = None


class ModelPage(Page):
    version: Version | None = None
    location: Code | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LocationRow(BaseModel):
    code: str
    name: str
    latitude: float
    longitude: float


class ObservationRow(BaseModel):
    location: str
    source: str
    valid_at: datetime
    local_date: date
    rainfall_mm: float | None
    air_temperature_c: float | None
    relative_humidity_pct: float | None
    wind_speed_mps: float | None


class ForecastRow(BaseModel):
    location: str
    source: str
    valid_at: datetime
    issued_at: datetime | None
    received_at: datetime
    payload: dict


class RainfallRow(BaseModel):
    location: str
    source: str
    period_start: date
    period_end: date
    rainfall_total_mm: float | None
    rainfall_hours: int
    loaded_hours: int
    expected_hours: int


class CoverageQuery(Locations):
    source: Code = "open-meteo-archive-era5"


class CoverageRow(BaseModel):
    location: str
    source: str
    first_date: date
    last_date: date
    days_with_rainfall: int
