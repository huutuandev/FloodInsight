"""Explicit, bounded acquisition of modeled flood covariates and reviewed evidence."""

from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
from time import sleep

import httpx

from .historical import POINTS

ELEVATION = "https://api.open-meteo.com/v1/elevation"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
MARINE = "https://marine-api.open-meteo.com/v1/marine"
SOIL = "soil_moisture_0_to_7cm"
SEA_LEVEL = "sea_level_height_msl"
COAST = (16.10, 108.28)
UTC = timezone.utc
OFFICIAL_REPORT = (
    "https://media.chinhphu.vn/"
    "chum-anh-luc-luong-chuc-nang-da-nang-giup-dan-khac-phuc-thiet-hai-mua-lu-102221015173026205.htm"
)


def fingerprint(payload):
    return sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


def retry_delay(header, attempt):
    if header.isascii() and header.isdigit() and len(header) <= 8:
        return min(30, int(header))
    if header:
        try:
            until = parsedate_to_datetime(header)
        except (ValueError, OverflowError):
            pass
        else:
            if until.tzinfo is not None:
                return min(30, max(0, (until - datetime.now(UTC)).total_seconds()))
    return 2 ** attempt


def fetch(client, url, params):
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError:
            if attempt == 2:
                raise
            sleep(2 ** attempt)
            continue
        if attempt < 2 and (response.status_code in (408, 429) or response.status_code >= 500):
            sleep(retry_delay(response.headers.get("Retry-After", ""), attempt))
            continue
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Expected a successful provider JSON object")
        return str(response.url), payload


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid numeric measurement or coordinate: expected {low} through {high}")
    return value


def elevation_rows(payload):
    values = payload.get("elevation")
    if not isinstance(values, list) or len(values) != len(POINTS):
        raise ValueError("Expected one elevation result per requested coordinate")
    for point, value in zip(POINTS, values):
        if value is not None:
            yield dict(location=point.code, latitude=point.latitude, longitude=point.longitude,
                       feature="elevation", value=number(value, -12000, 9000), unit="m")


def hourly_rows(payload, variable, unit, station, coordinates, bounds, start=None, end=None):
    if payload.get("utc_offset_seconds") != 0:
        raise ValueError("Expected UTC timestamps")
    units = payload.get("hourly_units", {})
    if units.get("time") != "unixtime" or units.get(variable) != unit:
        raise ValueError("Unexpected hourly units")
    series = payload.get("hourly", {})
    times, values = series.get("time"), series.get(variable)
    if not isinstance(times, list) or not isinstance(values, list) or not times or len(times) != len(values):
        raise ValueError("Invalid hourly axis or variable array")
    if any(type(epoch) is not int or not 0 <= epoch <= 253402300799 or epoch % 3600 for epoch in times):
        raise ValueError("Expected hourly UTC Unix timestamps")
    if any(current - previous != 3600 for previous, current in zip(times, times[1:])):
        raise ValueError("Hourly axis must be contiguous and strictly ordered")
    if start is not None and (len(times) != ((end - start).days + 1) * 24
                              or datetime.fromtimestamp(times[0], UTC) != datetime.combine(start, time.min, UTC)):
        raise ValueError("Archive axis differs from the requested UTC date range")
    grid = (number(payload.get("latitude"), -90, 90), number(payload.get("longitude"), -180, 180))
    for epoch, value in zip(times, values):
        if value is not None:
            yield dict(station_key=station, variable=variable, valid_at=datetime.fromtimestamp(epoch, UTC),
                       latitude=coordinates[0], longitude=coordinates[1], grid_latitude=grid[0],
                       grid_longitude=grid[1], value=number(value, *bounds), unit=unit)


def batch(code, provider, dataset, ref, payload, rows, kind, metadata, licence="CC BY 4.0"):
    return dict(code=code, provider=provider, dataset=dataset, source_ref=ref,
                sha256=fingerprint(payload), retrieved_at=datetime.now(UTC), licence=licence,
                attribution=metadata["attribution"], metadata=metadata, kind=kind, rows=list(rows))


def collect(client, dataset, start=None, end=None):
    if dataset == "official-events":
        # This indexed entry describes a reported event window, not a geocoded point observation.
        event = dict(event_key="da-nang-2022-10-14", name="Da Nang October 2022 flood",
                     started_at="2022-10-14T00:00:00+07:00", ended_before="2022-10-16T00:00:00+07:00",
                     locality_as_reported="Đà Sơn, Hòa Khánh Nam, Liên Chiểu, Đà Nẵng",
                     boundary_vintage="Da Nang administrative geography as reported in October 2022")
        yield batch("vietnam-government-flood-reports", "Vietnam Government Portal",
                    "Reviewed flood report references", OFFICIAL_REPORT, event, [event], "events",
                    {"attribution": "Vietnam Government Portal (VGP)", "method": "manual evidence indexing",
                     "time_precision": "local civil days covered by report",
                     "published_date": "2022-10-15", "checksum_scope": "curated metadata"},
                    "Public report; redistribution licence not established; reference and facts only")
        return
    if dataset == "elevation":
        params = {"latitude": ",".join(str(p.latitude) for p in POINTS),
                  "longitude": ",".join(str(p.longitude) for p in POINTS)}
        ref, payload = fetch(client, ELEVATION, params)
        yield batch("open-meteo-cop-dem-glo90", "Open-Meteo", "Copernicus DEM GLO-90",
                    ref, payload, elevation_rows(payload), "terrain",
                    {"attribution": "Copernicus DEM via Open-Meteo", "resolution_m": 90,
                     "requested_samples": len(POINTS), "method": "provider point lookup"})
        return
    if dataset == "soil-moisture":
        if start is None or end is None or not 0 <= (end - start).days <= 30:
            raise ValueError("Soil moisture requires an ordered date range of up to 31 UTC days")
        if start < date(1940, 1, 1) or end > datetime.now(UTC).date() - timedelta(days=5):
            raise ValueError("ERA5 requests must begin in 1940 or later and end at least five UTC days ago")
        for point in POINTS:
            ref, payload = fetch(client, ARCHIVE, dict(latitude=point.latitude, longitude=point.longitude,
                                 start_date=start.isoformat(), end_date=end.isoformat(), models="era5",
                                 timezone="GMT", timeformat="unixtime", hourly=SOIL))
            rows = [row | {"location": point.code} for row in hourly_rows(
                payload, SOIL, "m³/m³", point.code, (point.latitude, point.longitude), (0, 1), start, end)]
            yield batch("open-meteo-archive-era5", "Open-Meteo", "Historical Weather ERA5",
                        ref, {key: value for key, value in payload.items() if key != "generationtime_ms"},
                        rows, "hydrology",
                        {"attribution": "Copernicus ERA5 via Open-Meteo", "kind": "reanalysis",
                         "station": point.code, "requested": [point.latitude, point.longitude],
                         "returned": [payload["latitude"], payload["longitude"]],
                         "resolution_degrees": 0.25, "expected_samples": ((end - start).days + 1) * 24})
        return
    if dataset != "coastal-sea-level":
        raise ValueError("Unknown flood dataset")
    ref, payload = fetch(client, MARINE, dict(latitude=COAST[0], longitude=COAST[1], hourly=SEA_LEVEL,
                         timezone="GMT", timeformat="unixtime", forecast_days=1, cell_selection="sea"))
    yield batch("open-meteo-marine", "Open-Meteo", "Marine modeled sea level",
                ref, {key: value for key, value in payload.items() if key != "generationtime_ms"},
                hourly_rows(payload, SEA_LEVEL, "m", "da-nang-offshore", COAST, (-30, 30)), "hydrology",
                {"attribution": "Open-Meteo and Copernicus Marine Service", "kind": "modeled_marine",
                 "station": "da-nang-offshore", "requested": list(COAST),
                 "returned": [payload["latitude"], payload["longitude"]],
                 "expected_samples": 24, "vertical_reference": "mean sea level",
                 "issue_time": None})
