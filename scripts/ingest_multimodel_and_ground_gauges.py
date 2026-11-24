"""Import forecasts from named Open-Meteo models into the warehouse.

VRAIN is deliberately not imported here: the repository currently has no licensed,
machine-readable gauge observations. In particular, daily storm totals must never
be expanded into fabricated hourly observations.
"""
import argparse
from contextlib import contextmanager
import hashlib
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import create_engine, text

# Allow running this file directly from the repository root with the warehouse venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "warehouse-service"))
from floodinsight_warehouse.config import DatabaseSettings

LOG = logging.getLogger("floodinsight.multi_model_import")
API_URL = "https://api.open-meteo.com/v1/forecast"
LOCK_KEY = 0x464C4F4F444D4C31
VARIABLES = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m",
             "precipitation", "precipitation_probability", "cape")
UNITS = {"temperature_2m": "°C", "relative_humidity_2m": "%", "wind_speed_10m": "m/s",
         "precipitation": "mm", "precipitation_probability": "%", "cape": "J/kg"}
MEASURES = {
    "rainfall_mm": ("precipitation", 0, 1_000_000),
    "air_temperature_c": ("temperature_2m", -100, 70),
    "relative_humidity_pct": ("relative_humidity_2m", 0, 100),
    "wind_speed_mps": ("wind_speed_10m", 0, 100_000),
}
SOURCES = (
    {"code": "open-meteo-ecmwf-ifs", "provider": "Open-Meteo / ECMWF",
     "dataset": "ECMWF IFS 0.25 forecast", "model": "ecmwf_ifs025",
     "name": "ECMWF IFS 0.25", "reference": "https://open-meteo.com/en/docs"},
    {"code": "open-meteo-gfs-seamless", "provider": "Open-Meteo / NOAA",
     "dataset": "GFS Seamless forecast", "model": "gfs_seamless",
     "name": "NOAA GFS Seamless", "reference": "https://open-meteo.com/en/docs"},
)


class ImportErrorDetail(Exception):
    pass


@contextmanager
def exclusive_import(engine):
    connection = engine.connect()
    try:
        if not connection.execute(text("SELECT pg_try_advisory_lock(:key)"),
                                  {"key": LOCK_KEY}).scalar_one():
            connection.commit()
            raise RuntimeError("Another multi-model import is already running")
        connection.commit()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            connection.commit()
    finally:
        connection.close()


def fetch_forecast(http_url, point, model, days, timeout):
    query = urlencode({
        "latitude": point["latitude"], "longitude": point["longitude"],
        "hourly": ",".join(VARIABLES), "models": model,
        "forecast_days": days, "timezone": "GMT", "timeformat": "unixtime",
        "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm",
    })
    request = Request(f"{http_url}?{query}", headers={"User-Agent": "FloodInsight/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
            received_at = datetime.now(timezone.utc)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise ImportErrorDetail(f"provider request/JSON failed: {type(error).__name__}") from error
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ImportErrorDetail("provider response has no hourly object")
    if payload.get("utc_offset_seconds") != 0:
        raise ImportErrorDetail("provider response is not in UTC")
    units = payload.get("hourly_units")
    if not isinstance(units, dict) or any(units.get(name) != unit for name, unit in UNITS.items()):
        raise ImportErrorDetail("provider returned unexpected or missing measurement units")
    for coordinate in ("latitude", "longitude"):
        value = payload.get(coordinate)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ImportErrorDetail(f"provider response has invalid {coordinate}")
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ImportErrorDetail("provider response has an empty time axis")
    if any(not isinstance(hourly.get(name), list) or len(hourly[name]) != len(times)
           for name in VARIABLES):
        raise ImportErrorDetail("provider hourly variables do not match the time axis")
    parsed = []
    for value in times:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ImportErrorDetail("provider timestamp is not a Unix epoch")
        instant = datetime.fromtimestamp(value, timezone.utc)
        if instant.minute or instant.second or instant.microsecond:
            raise ImportErrorDetail("provider timestamp is not an hourly boundary")
        parsed.append(instant)
    if any(right <= left for left, right in zip(parsed, parsed[1:])):
        raise ImportErrorDetail("provider timestamps are not strictly increasing")
    return received_at, hourly, parsed, payload


def normalized_measure(hourly, name, index):
    value = hourly[name][index]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImportErrorDetail(f"{name} contains a non-numeric value")
    low, high = next((bounds[1], bounds[2]) for bounds in MEASURES.values() if bounds[0] == name)
    if not low <= value <= high:
        raise ImportErrorDetail(f"{name} is outside accepted physical bounds")
    return value


def register_source(conn, source):
    row = conn.execute(text("""
        INSERT INTO data_sources (code, provider, dataset, reference_url)
        VALUES (:code, :provider, :dataset, :reference)
        ON CONFLICT (code) DO UPDATE SET provider = EXCLUDED.provider,
            dataset = EXCLUDED.dataset, reference_url = EXCLUDED.reference_url
        RETURNING id
    """), {key: source[key] for key in ("code", "provider", "dataset", "reference")}).one()
    conn.execute(text("""
        INSERT INTO dim_weather_source (data_source_id, name)
        VALUES (:id, :name)
        ON CONFLICT (data_source_id) DO UPDATE SET name = EXCLUDED.name
    """), {"id": row.id, "name": source["name"]})
    return row.id, conn.execute(text(
        "SELECT id FROM dim_weather_source WHERE data_source_id = :id"
    ), {"id": row.id}).scalar_one()


def start_run(engine, source_id):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE ingestion_runs SET status = 'failed', records_inserted = coalesce(records_inserted, 0),
                finished_at = GREATEST(clock_timestamp(), started_at),
                error_message = 'Importer worker was interrupted'
            WHERE source_id = :source AND status = 'running'
        """), {"source": source_id})
        return conn.execute(text("""
            INSERT INTO ingestion_runs (source_id, run_key, trigger)
            VALUES (:source, :key, 'manual') RETURNING id
        """), {"source": source_id, "key": uuid4().hex}).scalar_one()


def finish_run(engine, run_id, status, count, error=None):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE ingestion_runs SET status = :status, records_inserted = :count,
                finished_at = GREATEST(clock_timestamp(), started_at), error_message = :error
            WHERE id = :id AND status = 'running'
        """), {"status": status, "count": count, "error": error, "id": run_id})


def import_point(engine, source_id, run_id, point, model, days, timeout, api_url):
    received, hourly, instants, response = fetch_forecast(api_url, point, model, days, timeout)
    grid = {key: response.get(key) for key in ("latitude", "longitude", "elevation")}
    records = []
    for index, instant in enumerate(instants):
        values = {name: hourly[name][index] for name in VARIABLES}
        measures = {column: normalized_measure(hourly, name, index)
                    for column, (name, _, _) in MEASURES.items()}
        if not any(value is not None for value in measures.values()):
            continue
        records.append((instant, values, measures))

    inserted = 0
    with engine.begin() as conn:
        for instant, values, _measures in records:
            probability = values["precipitation_probability"]
            cape = values["cape"]
            if probability is not None and (not isinstance(probability, (int, float)) or not 0 <= probability <= 100):
                raise ImportErrorDetail("precipitation_probability is outside [0, 100]")
            if cape is not None and (not isinstance(cape, (int, float)) or cape < 0):
                raise ImportErrorDetail("cape is outside its valid range")
            payload = {"kind": "hourly", "model": model, "location": {
                "code": point["code"], "name": point["name"], "latitude": float(point["latitude"]),
                "longitude": float(point["longitude"])}, "grid": grid,
                "issued_at": None,
                "units": UNITS, "values": values}
            result = conn.execute(text("""
                INSERT INTO raw_weather_forecasts
                  (source_id, ingestion_run_id, source_location_key, valid_at, issued_at,
                   received_at, snapshot_hash, payload)
                VALUES (:source, :run, :location, :valid, NULL, :received, :digest, :payload)
                ON CONFLICT (source_id, source_location_key, valid_at, snapshot_hash)
                  WHERE snapshot_hash IS NOT NULL DO NOTHING
            """), {"source": source_id, "run": run_id, "location": point["code"],
                   "valid": instant, "received": received,
                   "digest": hashlib.sha256(json.dumps(
                       payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                   ).encode()).hexdigest(), "payload": json.dumps(payload, allow_nan=False)})
            inserted += result.rowcount
    return inserted


def run_import(args):
    engine = create_engine(DatabaseSettings().url(), pool_pre_ping=True)
    failures = []
    try:
        with exclusive_import(engine):
            with engine.connect() as conn:
                points = conn.execute(text(
                    "SELECT id, code, name, latitude, longitude FROM dim_location ORDER BY code"
                )).mappings().all()
                if not points:
                    raise RuntimeError("No locations in dim_location; run warehouse backfill first")
            source_ids = {}
            with engine.begin() as conn:
                for source in SOURCES:
                    source_ids[source["code"]] = register_source(conn, source)
            for source in SOURCES:
                source_id, _weather_source_id = source_ids[source["code"]]
                run_id = start_run(engine, source_id)
                inserted = 0
                errors = []
                for point in points:
                    for attempt in range(args.retries):
                        try:
                            inserted += import_point(engine, source_id, run_id, point,
                                                     source["model"], args.days,
                                                     args.timeout, args.url)
                            LOG.info("Imported %s %s", source["code"], point["code"])
                            break
                        except Exception as error:
                            message = f"{point['code']}: {type(error).__name__}: {error}"
                            if attempt + 1 == args.retries:
                                errors.append(message)
                                LOG.exception("Import failed for %s %s", source["code"], point["code"])
                            else:
                                time.sleep(min(2 ** attempt, 10))
                status = "failed" if errors else "succeeded"
                finish_run(engine, run_id, status, inserted, "; ".join(errors)[:4000] or None)
                if errors:
                    failures.append(f"{source['code']} run {run_id}: " + "; ".join(errors))
                LOG.info("Run %s %s: inserted %d raw snapshots", run_id, status, inserted)
    finally:
        engine.dispose()
    if failures:
        raise RuntimeError("One or more source imports failed: " + " | ".join(failures))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, choices=range(1, 8), default=7)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--url", default=API_URL)
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_import(parse_args())
