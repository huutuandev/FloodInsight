from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

VARIABLES = {
    "precipitation": "mm",
    "rain": "mm",
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "m/s",
}


class DateRange(BaseModel):
    start_date: date
    end_date: date
    max_batches: Annotated[int, Field(ge=1, le=120)] = 5

    @model_validator(mode="after")
    def validate_dates(self) -> "DateRange":
        if self.start_date < date(1940, 1, 2):
            raise ValueError("The first full Vietnam calendar day in ERA5 is 1940-01-02")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.end_date > datetime.now(timezone.utc).date() - timedelta(days=5):
            raise ValueError("ERA5 dates must be at least five days behind the current UTC date")
        return self


class ETLRequest(DateRange):
    max_batches: Annotated[int, Field(ge=1, le=120)] = 20
    reprocess: bool = False
    after_batch_id: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0


class ForecastETLRequest(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> "ForecastETLRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days >= 31:
            raise ValueError("Forecast materialization is limited to 31 days per request")
        return self


class ForecastETLResult(BaseModel):
    start_date: date
    end_date: date
    rows_upserted: int
    locations: list[str]


class ArchiveHourlies(BaseModel):
    time: list[int]
    precipitation: list[FiniteFloat | None]
    rain: list[FiniteFloat | None]
    temperature_2m: list[FiniteFloat | None]
    relative_humidity_2m: list[FiniteFloat | None]
    wind_speed_10m: list[FiniteFloat | None]

    @model_validator(mode="after")
    def validate_axis(self) -> "ArchiveHourlies":
        if not self.time or any(len(getattr(self, name)) != len(self.time) for name in VARIABLES):
            raise ValueError("Hourly variables must match a nonempty time axis")
        if any(value % 3600 for value in self.time) or any(
            b <= a for a, b in zip(self.time, self.time[1:])
        ):
            raise ValueError("Provider timestamps must be strictly increasing UTC hours")
        return self


class ArchiveResponse(BaseModel):
    latitude: Annotated[FiniteFloat, Field(ge=-90, le=90)]
    longitude: Annotated[FiniteFloat, Field(ge=-180, le=180)]
    elevation: FiniteFloat | None = None
    utc_offset_seconds: Literal[0]
    hourly: ArchiveHourlies
    hourly_units: dict[str, str]

    @model_validator(mode="after")
    def validate_units(self) -> "ArchiveResponse":
        units = VARIABLES | {"time": "unixtime"}
        if any(self.hourly_units.get(name) != unit for name, unit in units.items()):
            raise ValueError("Unexpected Open-Meteo units")
        return self


class RunResult(BaseModel):
    id: int
    operation: Literal["backfill", "etl"]
    start_date: date
    end_date: date
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    progress: dict[str, int]
    error_message: str | None


class WarehouseStatus(BaseModel):
    runs: list[RunResult]
    downloaded_batches: int
    loaded_batches: int


class QualityReport(BaseModel):
    id: int
    location_code: str
    start_date: date
    end_date: date
    etl_run_id: int
    quality: dict
