import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from pydantic import ValidationError

from ..config import Settings
from ..schemas.ingestion import Snapshot
from ..schemas.open_meteo import ForecastResponse, SOIL_UNITS, VARIABLE_UNITS
from .locations import DANANG_POINTS, SamplingPoint


class ProviderError(Exception):
    pass


def retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(0, int(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is not None:
                    return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, OverflowError):
                pass
    return 2 ** attempt


class OpenMeteoClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def fetch(self) -> list[Snapshot]:
        batches = await asyncio.gather(
            *(self._fetch_location(point) for point in DANANG_POINTS),
            return_exceptions=True,
        )
        for batch in batches:
            if isinstance(batch, BaseException):
                raise batch
        return [snapshot for batch in batches for snapshot in batch]

    async def _fetch_location(self, point: SamplingPoint) -> list[Snapshot]:
        variables = ",".join(VARIABLE_UNITS)
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "current": variables,
            "hourly": ",".join((*VARIABLE_UNITS, *SOIL_UNITS)),
            "past_hours": self.settings.past_hours,
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "timeformat": "unixtime",
            "timezone": "GMT",
            "forecast_hours": self.settings.forecast_hours,
        }
        for attempt in range(self.settings.max_attempts):
            try:
                async with asyncio.timeout(self.settings.timeout_seconds):
                    response = await self.http.get(str(self.settings.open_meteo_url), params=params)
                    received_at = datetime.now(timezone.utc)
                    response.raise_for_status()
            except (httpx.TransportError, TimeoutError) as error:
                reason = "request timed out or transport failed"
                cause = error
                delay = 2 ** attempt
            except httpx.HTTPStatusError as error:
                code = error.response.status_code
                reason = f"HTTP {code}"
                if code not in (408, 429) and not 500 <= code <= 599:
                    raise ProviderError(f"{point.code}: {reason}") from error
                cause = error
                delay = retry_delay(error.response, attempt)
            else:
                try:
                    forecast = ForecastResponse.model_validate_json(response.content)
                except ValidationError as error:
                    raise ProviderError(f"{point.code}: invalid Open-Meteo response") from error
                if len(forecast.hourly.time) != self.settings.forecast_hours + self.settings.past_hours:
                    raise ProviderError(f"{point.code}: incomplete hourly series")
                return to_snapshots(point, forecast, received_at)

            if attempt + 1 == self.settings.max_attempts or delay > 30:
                raise ProviderError(f"{point.code}: Open-Meteo {reason}") from cause
            await asyncio.sleep(delay)
        raise AssertionError("max_attempts must be positive")


def to_snapshots(
    point: SamplingPoint, forecast: ForecastResponse, received_at: datetime
) -> list[Snapshot]:
    context = {
        "location": asdict(point),
        "grid": {
            "latitude": forecast.latitude,
            "longitude": forecast.longitude,
            "elevation_m": forecast.elevation,
        },
        "units": VARIABLE_UNITS,
    }

    def snapshot(kind: str, epoch: int, interval: int, measurements: dict) -> Snapshot:
        return Snapshot(
            location_code=point.code,
            valid_at=datetime.fromtimestamp(epoch, timezone.utc),
            received_at=received_at,
            payload=context | {"kind": kind, "interval_seconds": interval, "values": measurements,
                               "units": VARIABLE_UNITS | {key: SOIL_UNITS[key] for key in measurements if key in SOIL_UNITS}},
        )

    current = forecast.current
    rows = [
        snapshot(
            "current",
            current.time,
            current.interval,
            current.model_dump(include=set(VARIABLE_UNITS)),
        )
    ]
    hourly = forecast.hourly
    keys = (*VARIABLE_UNITS, *(key for key in SOIL_UNITS if getattr(hourly, key) is not None))
    rows.extend(
        snapshot("hourly", valid_at, 3600, {key: getattr(hourly, key)[i] for key in keys})
        for i, valid_at in enumerate(hourly.time)
    )
    return rows
