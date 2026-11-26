from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

VARIABLE_UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "m/s",
    "precipitation": "mm",
    "rain": "mm",
    "showers": "mm",
    "pressure_msl": "hPa",
    "weather_code": "wmo code",
}

SOIL_UNITS = {f"soil_moisture_{top}_to_{bottom}cm": "m\u00b3/m\u00b3"
              for top, bottom in ((0, 1), (1, 3), (3, 9), (9, 27), (27, 81))}
SoilMoisture = Annotated[FiniteFloat, Field(ge=0, le=1)]

Nonnegative = Annotated[FiniteFloat, Field(ge=0)]
Percentage = Annotated[FiniteFloat, Field(ge=0, le=100)]
EpochSeconds = Annotated[int, Field(ge=0, le=253402300799)]
WeatherCode = Annotated[int, Field(ge=0, le=99)]


class WeatherValues(BaseModel):
    model_config = ConfigDict(strict=True)

    temperature_2m: FiniteFloat | None
    relative_humidity_2m: Percentage | None
    wind_speed_10m: Nonnegative | None
    precipitation: Nonnegative | None
    rain: Nonnegative | None
    showers: Nonnegative | None
    pressure_msl: Nonnegative | None
    weather_code: WeatherCode | None


class CurrentWeather(WeatherValues):
    time: EpochSeconds
    interval: Annotated[int, Field(gt=0, le=3600)]


class HourlyWeather(BaseModel):
    model_config = ConfigDict(strict=True)

    time: Annotated[list[EpochSeconds], Field(min_length=1, max_length=120)]
    temperature_2m: list[FiniteFloat | None]
    relative_humidity_2m: list[Percentage | None]
    wind_speed_10m: list[Nonnegative | None]
    precipitation: list[Nonnegative | None]
    rain: list[Nonnegative | None]
    showers: list[Nonnegative | None]
    pressure_msl: list[Nonnegative | None]
    weather_code: list[WeatherCode | None]

    soil_moisture_0_to_1cm: list[SoilMoisture | None] | None = None
    soil_moisture_1_to_3cm: list[SoilMoisture | None] | None = None
    soil_moisture_3_to_9cm: list[SoilMoisture | None] | None = None
    soil_moisture_9_to_27cm: list[SoilMoisture | None] | None = None
    soil_moisture_27_to_81cm: list[SoilMoisture | None] | None = None

    @model_validator(mode="after")
    def validate_time_series(self) -> "HourlyWeather":
        if any(len(getattr(self, key)) != len(self.time) for key in VARIABLE_UNITS):
            raise ValueError("Hourly variable lengths must match the time axis")
        if any(len(values) != len(self.time) for key in SOIL_UNITS if (values := getattr(self, key)) is not None):
            raise ValueError("Hourly soil moisture lengths must match the time axis")
        if self.time[0] % 3600 or any(b - a != 3600 for a, b in zip(self.time, self.time[1:])):
            raise ValueError("Hourly valid times must be consecutive UTC hour boundaries")
        return self


class ForecastResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    latitude: Annotated[FiniteFloat, Field(ge=-90, le=90)]
    longitude: Annotated[FiniteFloat, Field(ge=-180, le=180)]
    elevation: FiniteFloat | None = None
    utc_offset_seconds: Literal[0]
    current: CurrentWeather
    current_units: dict[str, str]
    hourly: HourlyWeather
    hourly_units: dict[str, str]

    @model_validator(mode="after")
    def validate_units(self) -> "ForecastResponse":
        hourly = VARIABLE_UNITS | {"time": "unixtime"}
        current = hourly | {"interval": "seconds"}
        if any(self.hourly_units.get(key) != unit for key, unit in hourly.items()):
            raise ValueError("Unexpected hourly units")
        if any(self.hourly_units.get(key) != unit for key, unit in SOIL_UNITS.items()
               if getattr(self.hourly, key) is not None):
            raise ValueError("Unexpected soil moisture units")
        if any(self.current_units.get(key) != unit for key, unit in current.items()):
            raise ValueError("Unexpected current units")
        return self
