from datetime import date

from pydantic import BaseModel, Field, model_validator


class LocationFilters(BaseModel):
    location: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0, le=1_000_000)


class Filters(LocationFilters):
    start_date: date
    end_date: date
    source: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date < date(1900, 1, 1) or self.end_date > date(2200, 12, 30):
            raise ValueError("Date outside the warehouse calendar")
        if not 0 <= (self.end_date - self.start_date).days < 3660:
            raise ValueError("Select an inclusive range of up to 3,660 days")
        return self


class CoverageFilters(LocationFilters):
    source: str = Field(default="open-meteo-archive-era5", min_length=1, max_length=100)
