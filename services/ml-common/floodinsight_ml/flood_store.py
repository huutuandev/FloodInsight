"""Shared warehouse reader for issuance-safe flood features."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re

from .availability import ERA5_DELAY
from .flood_features import HOUR, TARGET, grid, make_row

ERA5 = "open-meteo-archive-era5"
FORECAST = "open-meteo-forecast-api"

QUERIES = {
    "rain": """
        SELECT r.id, l.code AS location, d.code AS source, f.hour_start_utc AS hour,
               r.received_at, r.payload->'grid' AS grid, f.rainfall_mm::float8 AS rain
        FROM fact_weather_hourly f JOIN dim_location l ON l.id = f.location_id
        JOIN dim_weather_source s ON s.id = f.weather_source_id
        JOIN data_sources d ON d.id = s.data_source_id
        JOIN raw_weather_observations r ON r.source_id = d.id AND r.source_location_key = l.code
            AND r.valid_at = f.hour_start_utc + interval '1 hour'
        WHERE d.code = :era5 AND f.hour_start_utc >= :history_start AND f.hour_start_utc < :end
          AND r.received_at <= :as_of AND r.payload->'units'->>'rain' = 'mm'
          AND f.rainfall_mm = CASE WHEN jsonb_typeof(r.payload->'values'->'rain') = 'number'
              THEN round((r.payload->'values'->>'rain')::numeric, 3) END
        ORDER BY l.code, f.hour_start_utc
    """,
    "forecast": """
        SELECT r.id, receipt.run_id, r.source_location_key AS location, d.code AS source,
               receipt.received_at, r.valid_at, r.issued_at, r.payload->'grid' AS grid,
               CASE WHEN jsonb_typeof(r.payload->'values'->'rain') = 'number'
                    THEN (r.payload->'values'->>'rain')::float8 END AS rain
        FROM raw_weather_forecasts r JOIN data_sources d ON d.id = r.source_id
        JOIN forecast_snapshot_receipts receipt ON receipt.snapshot_id = r.id
        WHERE d.code = :forecast AND r.valid_at > :start AND r.valid_at <= :target_end
          AND receipt.received_at <= :end AND r.payload->>'kind' = 'hourly'
          AND r.payload->>'interval_seconds' = '3600' AND r.payload->'units'->>'rain' = 'mm'
        ORDER BY receipt.received_at, receipt.run_id, r.id
    """,
    "terrain": """
        SELECT f.id, l.code AS location, d.code AS source, f.feature, f.unit, f.value,
               a.retrieved_at AS available_at
        FROM flood_terrain_features f JOIN flood_dataset_assets a ON a.id = f.asset_id
        JOIN dim_location l ON l.id = f.location_id JOIN data_sources d ON d.id = a.source_id
        WHERE a.retrieved_at <= :end AND f.latitude = l.latitude::float8 AND f.longitude = l.longitude::float8
          AND ((d.code = 'copernicus-dem-glo30' AND (f.feature, f.unit) IN
               (('elevation', 'm'), ('surface_slope', 'degree')))
            OR (d.code = 'esa-worldcover-2021-v200' AND (f.feature, f.unit) IN
               (('worldcover_class', 'class_code'), ('worldcover_built_up_fraction_11x11', 'fraction'))))
        ORDER BY a.retrieved_at, a.id, f.id
    """,
    "hydrology": """
        SELECT h.id, l.code AS location, d.code AS source, h.variable, h.value, h.valid_at,
               a.retrieved_at AS available_at,
               jsonb_build_object('latitude', h.grid_latitude, 'longitude', h.grid_longitude) AS grid
        FROM flood_hydrology_observations h JOIN flood_dataset_assets a ON a.id = h.asset_id
        JOIN data_sources d ON d.id = a.source_id LEFT JOIN dim_location l ON l.id = h.location_id
        WHERE a.retrieved_at <= :as_of AND h.valid_at > :history_start AND h.valid_at <= :end
          AND ((d.code = :era5 AND h.variable = 'soil_moisture_0_to_7cm' AND h.unit = 'm³/m³'
                AND h.latitude = l.latitude::float8 AND h.longitude = l.longitude::float8)
            OR (d.code = 'open-meteo-marine' AND h.station_key = 'da-nang-offshore'
                AND h.variable = 'sea_level_height_msl' AND h.unit = 'm' AND h.location_id IS NULL))
        ORDER BY h.valid_at, a.retrieved_at, h.id
    """,
    "observations": """
        SELECT o.id, o.location_id, l.code AS location, d.code AS source,
               o.observed_at, o.latitude, o.longitude, o.spatial_uncertainty_m,
               o.label, o.quality, o.coverage_evidence, o.coverage_start, o.coverage_end, o.coverage_radius_m,
               e.event_key, e.started_at AS event_start, e.ended_before AS event_end,
               greatest(o.observed_at, a.retrieved_at, ea.retrieved_at) AS available_at
        FROM flood_observations o JOIN flood_dataset_assets a ON a.id = o.asset_id
        JOIN data_sources d ON d.id = a.source_id LEFT JOIN dim_location l ON l.id = o.location_id
        LEFT JOIN flood_events e ON e.id = o.event_id
        LEFT JOIN flood_dataset_assets ea ON ea.id = e.asset_id
        WHERE a.retrieved_at <= :as_of AND o.observed_at <= :as_of
          AND o.observed_at >= :label_history_start
        ORDER BY o.observed_at, o.id
    """,
}

GRID_INVENTORY = """
    WITH observations AS (
        SELECT source_id, source_location_key, valid_at, received_at, payload
        FROM raw_weather_observations
        UNION ALL
        SELECT source_id, source_location_key, valid_at, received_at, payload
        FROM raw_weather_forecasts WHERE payload->>'kind' = 'hourly'
    )
    SELECT d.code AS source, o.payload->'grid'->'latitude' AS latitude,
           o.payload->'grid'->'longitude' AS longitude,
           array_agg(DISTINCT o.source_location_key ORDER BY o.source_location_key) AS points,
           count(*) AS raw_rows, count(DISTINCT o.valid_at) AS distinct_valid_times
    FROM observations o JOIN data_sources d ON d.id = o.source_id
    WHERE o.received_at <= :as_of AND d.code IN (:era5, :forecast)
      AND jsonb_typeof(o.payload->'grid'->'latitude') = 'number'
      AND jsonb_typeof(o.payload->'grid'->'longitude') = 'number'
    GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""


def read(execute, start, end, as_of, *, include_inventory=True):
    params = dict(start=start, end=end, as_of=as_of, target_end=end + TARGET, era5=ERA5, forecast=FORECAST,
                  history_start=start - ERA5_DELAY - 72 * HOUR, label_history_start=start - timedelta(days=365))
    points = list(execute("SELECT id, code, latitude, longitude FROM dim_location ORDER BY code", {}))
    inputs = defaultdict(lambda: defaultdict(list))
    evidence = []
    for kind, query in QUERIES.items():
        for row in execute(query, params):
            row = dict(row)
            if kind in ("rain", "forecast", "hydrology"):
                cell = grid(row)
                valid = row["hour"] + HOUR if kind == "rain" else row["valid_at"]
                row["weather_bin"] = (cell, valid) if cell else None
            if kind == "observations":
                if row["available_at"] > as_of:
                    continue
                evidence.append(row)
            inputs[row["location"]][kind].append(row)
    grids = [dict(row) for row in execute(GRID_INVENTORY, params)] if include_inventory else []
    return points, inputs, evidence, grids


def postgres_read(conn, start, end, as_of, *, include_inventory=True):
    def execute(sql, params):
        query = re.sub(r"(?<!:):([a-z_][a-z_0-9]*)", r"%(\1)s", sql)
        return conn.execute(query, params)
    return read(execute, start, end, as_of, include_inventory=include_inventory)


def current_features(conn, issuance):
    points, inputs, _, _ = postgres_read(conn, issuance, issuance, issuance, include_inventory=False)
    for point in points:
        source = inputs[point["code"]]
        features = {name: source[name] for name in QUERIES}
        features["hydrology"] = source["hydrology"] + inputs[None]["hydrology"]
        yield make_row(point, issuance, issuance, "operational", features, include_validity=True)


def resolve_issuance(value, now=None):
    now = now or datetime.now(timezone.utc)
    issue = value.astimezone(timezone.utc) if value is not None else now.replace(minute=0, second=0, microsecond=0)
    if issue > now or any((issue.minute, issue.second, issue.microsecond)):
        raise ValueError("Use a whole UTC hour at or before the current time")
    return issue
