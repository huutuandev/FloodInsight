from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from time import sleep
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from ..schemas.historical import ArchiveResponse, VARIABLES

VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@dataclass(frozen=True)
class SamplingPoint:
    code: str
    name: str
    latitude: float
    longitude: float


# Same documented point identifiers as the live ingestion service.
POINTS = (
    SamplingPoint("hai-chau", "Hải Châu", 16.076345, 108.221783),
    SamplingPoint("thanh-khe", "Thanh Khê", 16.071259, 108.191634),
    SamplingPoint("lien-chieu", "Liên Chiểu", 16.07272, 108.15815),
    SamplingPoint("cam-le", "Cẩm Lệ", 16.0153, 108.2013),
    SamplingPoint("ngu-hanh-son", "Ngũ Hành Sơn", 16.008333, 108.2525),
    SamplingPoint("son-tra", "Sơn Trà", 16.1011, 108.2612),
    SamplingPoint("hoa-vang", "Hòa Vang (Hòa Phong)", 15.9867, 108.1408),
    SamplingPoint("hoa-bac", "Hòa Vang (Hòa Bắc)", 16.1472, 108.0167),
    SamplingPoint("hoa-khuong", "Hòa Vang (Hòa Khương)", 15.9458, 108.1069),
)


def utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return tuple(
        datetime.combine(day, time.min, VIETNAM).astimezone(timezone.utc)
        for day in (start, end + DAY)
    )


def month_batches(start: date, end: date):
    while start <= end:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = min(end, next_month - DAY)
        yield start, last
        start = last + DAY


@dataclass(frozen=True)
class ArchiveRecord:
    valid_at: datetime
    received_at: datetime
    payload: dict


class ArchiveError(Exception):
    pass


class ArchiveClient:
    def __init__(self, http: httpx.Client, url: str, attempts: int):
        self.http = http
        self.url = url
        self.attempts = attempts

    def fetch(self, point: SamplingPoint, start: date, end: date) -> list[ArchiveRecord]:
        lower, upper = utc_bounds(start, end)
        params = {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "start_date": lower.date().isoformat(),
            "end_date": upper.date().isoformat(),
            "models": "era5",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
            "wind_speed_unit": "ms",
            "hourly": ",".join(VARIABLES),
        }
        for attempt in range(self.attempts):
            delay = 2 ** attempt
            try:
                response = self.http.get(self.url, params=params)
                received_at = datetime.now(timezone.utc)
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status not in (408, 429) and not 500 <= status <= 599:
                    raise ArchiveError(f"Open-Meteo returned HTTP {status}") from error
                header = error.response.headers.get("Retry-After", "")
                if header.isascii() and header.isdecimal() and len(header) < 10:
                    delay = max(delay, int(header))
                reason = f"HTTP {status}"
            except httpx.TransportError:
                reason = "timeout or transport error"
            else:
                try:
                    parsed = ArchiveResponse.model_validate_json(response.content)
                except ValidationError as error:
                    raise ArchiveError("Invalid Open-Meteo archive response") from error
                return archive_records(parsed, point, lower, upper, received_at)
            if attempt + 1 == self.attempts or delay > 30:
                raise ArchiveError(f"Open-Meteo archive request failed: {reason}")
            sleep(delay)
        raise AssertionError("At least one attempt is required")


def archive_records(
    response: ArchiveResponse, point: SamplingPoint, lower: datetime, upper: datetime,
    received_at: datetime,
) -> list[ArchiveRecord]:
    metadata = {
        "model": "era5",
        "location": asdict(point),
        "grid": {"latitude": response.latitude, "longitude": response.longitude,
                 "elevation_m": response.elevation},
        "units": VARIABLES,
    }
    hourly = response.hourly
    records = [
        ArchiveRecord(datetime.fromtimestamp(epoch, timezone.utc), received_at,
                      metadata | {"values": {field: getattr(hourly, field)[index] for field in VARIABLES}})
        for index, epoch in enumerate(hourly.time)
        if lower.timestamp() <= epoch <= upper.timestamp()
    ]
    if not any(value is not None for row in records for value in row.payload["values"].values()):
        raise ArchiveError("Archive has no available measurements in the requested batch")
    return records

