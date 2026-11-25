from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

Location = Annotated[str, Field(min_length=1, max_length=100)]
Version = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class Window(BaseModel):
    start_date: date
    end_date: date
    location: Location | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date < date(1940, 1, 2) or self.end_date > date(2200, 12, 30):
            raise ValueError("Dates are outside the supported calendar")
        if not 0 <= (self.end_date - self.start_date).days < 3660:
            raise ValueError("Specify an ordered range of at most 3,660 days")
        return self


class RunWindow(Window):
    version: Version | None = None

