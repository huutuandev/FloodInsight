"""Operator commands for Phase 1 flood data acquisition and coverage audits."""

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from .config import DatabaseSettings
from .services.flood_rasters import raster_batch
from .services.flood_sources import POINTS, collect, fingerprint


TABLES = {
    "events": ("flood_events", ("asset_id", "event_key", "name", "started_at", "ended_before",
                               "locality_as_reported", "boundary_vintage")),
    "terrain": ("flood_terrain_features", ("asset_id", "location_id", "latitude", "longitude",
                                          "feature", "value", "unit")),
    "hydrology": ("flood_hydrology_observations", ("asset_id", "location_id", "station_key",
                  "variable", "valid_at", "latitude", "longitude", "grid_latitude", "grid_longitude",
                  "value", "unit", "sample_sha256")),
}


def ensure_points(conn):
    for point in POINTS:
        params = dict(code=point.code, name=point.name, latitude=point.latitude, longitude=point.longitude)
        conn.execute(text("""
            INSERT INTO dim_location (code, name, latitude, longitude)
            VALUES (:code, :name, :latitude, :longitude) ON CONFLICT (code) DO NOTHING
        """), params)
        stored = conn.execute(text("""
            SELECT id, latitude, longitude FROM dim_location WHERE code = :code
        """), params).one()
        if (float(stored.latitude), float(stored.longitude)) != (point.latitude, point.longitude):
            raise ValueError(f"Existing coordinates differ from the configured point {point.code}")
        yield point.code, stored.id


def save(conn, batches):
    counts = Counter()
    locations = dict(ensure_points(conn)) if any(
        "location" in row for batch in batches for row in batch["rows"]
    ) else {}
    for batch in batches:
        conn.execute(text("""
            INSERT INTO data_sources (code, provider, dataset)
            VALUES (:code, :provider, :dataset) ON CONFLICT (code) DO NOTHING
        """), batch)
        source_id = conn.scalar(text("SELECT id FROM data_sources WHERE code = :code"), batch)
        params = batch | {"source_id": source_id, "metadata": json.dumps(batch["metadata"])}
        asset_id = conn.scalar(text("""
            INSERT INTO flood_dataset_assets
                (source_id, source_ref, sha256, retrieved_at, licence, attribution, metadata)
            VALUES (:source_id, :source_ref, :sha256, :retrieved_at, :licence, :attribution, CAST(:metadata AS jsonb))
            ON CONFLICT (source_id, source_ref, sha256) DO NOTHING RETURNING id
        """), params)
        if asset_id is None:
            asset_id = conn.scalar(text("""
                SELECT id FROM flood_dataset_assets
                WHERE source_id = :source_id AND source_ref = :source_ref AND sha256 = :sha256
            """), params)
        else:
            counts["assets"] += 1
        kind = batch["kind"]
        table, columns = TABLES[kind]
        sql = text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                   f"({', '.join(':' + c for c in columns)}) ON CONFLICT DO NOTHING RETURNING id")
        for row in batch["rows"]:
            params = row | {"asset_id": asset_id, "location_id": locations.get(row.get("location"))}
            if kind == "hydrology":
                identity = {key: value for key, value in row.items() if key != "valid_at"}
                params["sample_sha256"] = fingerprint(identity | {"source": batch["code"]})
            counts[kind] += conn.scalar(sql, params) is not None
    return {kind: counts[kind] for kind in ("assets", *TABLES)}


AUDIT = {
    "weather_daily": """
        WITH days AS (
            SELECT l.code AS location, d.code AS source, f.local_date,
                   f.hours_with_rainfall,
                   f.local_date - lag(f.local_date) OVER (
                       PARTITION BY f.location_id, f.weather_source_id ORDER BY f.local_date
                   ) - 1 AS gap_days
            FROM fact_rainfall_daily f JOIN dim_location l ON l.id = f.location_id
            JOIN dim_weather_source s ON s.id = f.weather_source_id
            JOIN data_sources d ON d.id = s.data_source_id
        )
        SELECT location, source, min(local_date) AS first_date, max(local_date) AS last_date,
               count(*) AS days_with_rainfall, sum(coalesce(gap_days, 0)) AS missing_days_between,
               count(*) FILTER (WHERE hours_with_rainfall < extract(epoch FROM
                 warehouse_local_day_start(local_date + 1) - warehouse_local_day_start(local_date)) / 3600)
                 AS partial_days
        FROM days GROUP BY location, source ORDER BY location, source
    """,
    "weather_hourly_nulls": """
        SELECT count(*) AS rows, count(*) - count(rainfall_mm) AS missing_rain,
               count(*) - count(air_temperature_c) AS missing_temperature,
               count(*) - count(relative_humidity_pct) AS missing_humidity,
               count(*) - count(wind_speed_mps) AS missing_wind
        FROM fact_weather_hourly
    """,
    "historical_batch_quality": """
        SELECT location_code, count(*) AS downloaded, count(etl_run_id) AS loaded,
               coalesce(sum((quality->>'missing_raw_timestamps')::bigint), 0) AS missing_raw_timestamps
        FROM historical_batches GROUP BY location_code ORDER BY location_code
    """,
    "weather_provider_grids": """
        WITH weather AS (
            SELECT 'archive' AS feed, source_id, source_location_key, valid_at, received_at, payload
            FROM raw_weather_observations
            UNION ALL
            SELECT 'forecast', source_id, source_location_key, valid_at, received_at, payload
            FROM raw_weather_forecasts
        )
        SELECT feed, s.code AS source, source_location_key AS point, payload->'grid' AS grid,
               payload->'units'->>'rain' AS rain_unit, payload->'units'->>'precipitation' AS precipitation_unit,
               count(*) AS rows, min(valid_at) AS first_valid, max(valid_at) AS last_valid,
               min(received_at) AS first_received, max(received_at) AS last_received
        FROM weather JOIN data_sources s ON s.id = weather.source_id
        GROUP BY feed, s.code, point, grid, rain_unit, precipitation_unit ORDER BY feed, source, point
    """,
    "assets": """
        SELECT s.code AS source, count(*) AS assets, min(a.retrieved_at) AS first_retrieved,
               max(a.retrieved_at) AS last_retrieved
        FROM flood_dataset_assets a JOIN data_sources s ON s.id = a.source_id GROUP BY s.code ORDER BY s.code
    """,
    "events": """
        SELECT e.event_key, e.locality_as_reported, e.boundary_vintage,
               e.started_at, e.ended_before, a.source_ref
        FROM flood_events e JOIN flood_dataset_assets a ON a.id = e.asset_id ORDER BY e.started_at
    """,
    "labels": "SELECT label, quality, count(*) AS rows FROM flood_observations GROUP BY label, quality ORDER BY label, quality",
    "terrain": """
        SELECT l.code AS point, s.code AS source, f.feature, f.value, f.unit, f.latitude, f.longitude
        FROM flood_terrain_features f JOIN dim_location l ON l.id = f.location_id
        JOIN flood_dataset_assets a ON a.id = f.asset_id JOIN data_sources s ON s.id = a.source_id
        ORDER BY point, source, feature, f.id
    """,
    "hydrology": """
        WITH complete_soil_days AS (
            SELECT h.station_key, (h.valid_at AT TIME ZONE 'UTC')::date AS day
            FROM flood_hydrology_observations h
            JOIN flood_dataset_assets a ON a.id = h.asset_id
            JOIN data_sources s ON s.id = a.source_id
            WHERE s.code = 'open-meteo-archive-era5' AND h.variable = 'soil_moisture_0_to_7cm'
            GROUP BY h.station_key, day
            HAVING count(DISTINCT h.valid_at) = 24
        )
        SELECT s.code AS source, o.station_key, o.variable, o.unit, o.latitude, o.longitude,
               o.grid_latitude, o.grid_longitude, min(o.valid_at) AS first_valid,
               max(o.valid_at) AS last_valid, count(*) AS rows,
               count(DISTINCT o.valid_at) AS distinct_hours,
               (extract(epoch FROM max(o.valid_at) - min(o.valid_at)) / 3600)::bigint
                 + 1 - count(DISTINCT o.valid_at) AS missing_hours_between,
               CASE WHEN s.code = 'open-meteo-archive-era5' AND o.variable = 'soil_moisture_0_to_7cm'
                    THEN ARRAY(SELECT day FROM complete_soil_days
                               WHERE station_key = o.station_key ORDER BY day)
                    ELSE ARRAY[]::date[] END AS complete_utc_dates
        FROM flood_hydrology_observations o
        JOIN flood_dataset_assets a ON a.id = o.asset_id JOIN data_sources s ON s.id = a.source_id
        GROUP BY source, o.station_key, o.variable, o.unit, o.latitude, o.longitude,
                 o.grid_latitude, o.grid_longitude ORDER BY source, o.station_key
    """,
}


def audit(conn):
    report = {section: [dict(row) for row in conn.execute(text(query)).mappings()]
              for section, query in AUDIT.items()}
    report["counts"] = {
        table: conn.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in ("flood_dataset_assets", "flood_events", "flood_observations",
                      "flood_terrain_features", "flood_hydrology_observations")
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("dataset", choices=("elevation", "soil-moisture", "coastal-sea-level", "official-events"))
    ingest.add_argument("--start", type=date.fromisoformat)
    ingest.add_argument("--end", type=date.fromisoformat)
    ingest.add_argument("--dry-run", action="store_true")
    raster = commands.add_parser("raster")
    raster.add_argument("dataset", choices=("copernicus-dem", "worldcover"))
    raster.add_argument("path", type=Path)
    raster.add_argument("--dry-run", action="store_true")
    commands.add_parser("audit")
    args = parser.parse_args()
    if args.command == "ingest":
        if args.dataset != "soil-moisture" and (args.start is not None or args.end is not None):
            parser.error("--start and --end are only supported for soil-moisture")
        with httpx.Client(timeout=30.0) as client:
            batches = list(collect(client, args.dataset, args.start, args.end))
    elif args.command == "raster":
        batches = [raster_batch(args.dataset, args.path)]
    if args.command != "audit":
        summary = {"dataset": args.dataset, "batches": [
            batch["metadata"] | {"validated_rows": len(batch["rows"]), "source_ref": batch["source_ref"],
                                 "missing_samples": batch["metadata"].get(
                                     "expected_samples", batch["metadata"].get("requested_samples", len(batch["rows"]))
                                 ) - len(batch["rows"])}
            for batch in batches
        ]}
        if not args.dry_run:
            engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 5})
            with engine.begin() as conn:
                summary["inserted"] = save(conn, batches)
    else:
        engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 5})
        with engine.begin() as conn:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            summary = audit(conn)
    print(json.dumps(summary, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
