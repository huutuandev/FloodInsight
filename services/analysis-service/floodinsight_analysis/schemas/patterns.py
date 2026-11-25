from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

PatternName = Literal[
    "rainfall_daily", "rainfall_weekly", "rainfall_monthly",
    "rainfall_vs_humidity", "rainfall_vs_temperature", "rainfall_histogram",
    "monthly_trend", "monthly_seasonality", "correlation", "descriptive_statistics",
]


class PatternScope(BaseModel):
    location: Annotated[str, Field(min_length=1, max_length=100)]
    source: Annotated[str, Field(min_length=1, max_length=100)] = "open-meteo-archive-era5"
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_window(self) -> "PatternScope":
        if self.start_date < date(1900, 1, 1) or self.end_date > date(2200, 12, 31):
            raise ValueError("Analysis dates must be between 1900 and 2200")
        if not 0 <= (self.end_date - self.start_date).days < 3660:
            raise ValueError("Specify an increasing inclusive range of up to 3,660 days")
        return self


class PatternQuery(PatternScope):
    pattern: PatternName | None = None


class Pattern(BaseModel):
    name: PatternName
    status: Literal["ready", "insufficient_data"]
    option: dict
    metadata: dict


class StoredPattern(Pattern):
    generated_at: datetime

