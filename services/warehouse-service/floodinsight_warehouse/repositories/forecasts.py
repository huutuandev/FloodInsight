from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ..config import DatabaseSettings
from .historical import WarehouseBusy

SOURCE_CODE = "open-meteo-forecast-api"
LOCK_KEY = 0x464C4F4F44464F52

BOUNDS = text("""
    SELECT warehouse_local_day_start(:start_date) AS lower_bound,
           warehouse_local_day_start(CAST(:end_date AS date) + 1) AS upper_bound
""")

UNKNOWN_LOCATIONS = text("""
    SELECT DISTINCT r.source_location_key
    FROM raw_weather_forecasts r
    LEFT JOIN dim_location l ON l.code = r.source_location_key
    WHERE r.source_id = :source_id
      AND r.payload ->> 'kind' = 'hourly'
      AND r.payload ->> 'interval_seconds' = '3600'
      AND r.valid_at > :lower_bound AND r.valid_at <= :upper_bound
      AND l.id IS NULL
    ORDER BY r.source_location_key
""")

SNAPSHOT_ROWS = text("""
    SELECT DISTINCT r.source_location_key AS location
    FROM raw_weather_forecasts r
    WHERE r.source_id = :source_id
      AND r.payload ->> 'kind' = 'hourly'
      AND r.payload ->> 'interval_seconds' = '3600'
      AND r.valid_at > :lower_bound AND r.valid_at <= :upper_bound
      AND (r.payload -> 'values' ->> 'rain' IS NOT NULL
           OR r.payload -> 'values' ->> 'temperature_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'relative_humidity_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'wind_speed_10m' IS NOT NULL)
    ORDER BY r.source_location_key
""")

UPSERT_ISSUED = text("""
    INSERT INTO fact_weather_forecast_hourly
        (location_id, weather_source_id, hour_start_utc, issued_at,
         rainfall_mm, air_temperature_c, relative_humidity_pct, wind_speed_mps)
    SELECT l.id, ws.id, r.valid_at - INTERVAL '1 hour', r.issued_at,
           NULLIF(r.payload -> 'values' ->> 'rain', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'temperature_2m', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'relative_humidity_2m', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'wind_speed_10m', '')::numeric
    FROM raw_weather_forecasts r
    JOIN dim_location l ON l.code = r.source_location_key
    JOIN dim_weather_source ws ON ws.data_source_id = r.source_id
    WHERE r.source_id = :source_id
      AND r.issued_at IS NOT NULL
      AND r.payload ->> 'kind' = 'hourly'
      AND r.payload ->> 'interval_seconds' = '3600'
      AND r.valid_at > :lower_bound AND r.valid_at <= :upper_bound
      AND (r.payload -> 'values' ->> 'rain' IS NOT NULL
           OR r.payload -> 'values' ->> 'temperature_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'relative_humidity_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'wind_speed_10m' IS NOT NULL)
    ON CONFLICT (location_id, weather_source_id, hour_start_utc, issued_at)
        WHERE issued_at IS NOT NULL
    DO UPDATE SET rainfall_mm = EXCLUDED.rainfall_mm,
                  air_temperature_c = EXCLUDED.air_temperature_c,
                  relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                  wind_speed_mps = EXCLUDED.wind_speed_mps
""")

UPSERT_SNAPSHOTS = text("""
    INSERT INTO fact_weather_forecast_hourly
        (location_id, weather_source_id, hour_start_utc, issued_at, snapshot_received_at,
         rainfall_mm, air_temperature_c, relative_humidity_pct, wind_speed_mps)
    SELECT l.id, ws.id, r.valid_at - INTERVAL '1 hour', NULL, r.received_at,
           NULLIF(r.payload -> 'values' ->> 'rain', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'temperature_2m', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'relative_humidity_2m', '')::numeric,
           NULLIF(r.payload -> 'values' ->> 'wind_speed_10m', '')::numeric
    FROM raw_weather_forecasts r
    JOIN dim_location l ON l.code = r.source_location_key
    JOIN dim_weather_source ws ON ws.data_source_id = r.source_id
    WHERE r.source_id = :source_id
      AND r.issued_at IS NULL
      AND r.snapshot_hash IS NOT NULL
      AND r.payload ->> 'kind' = 'hourly'
      AND r.payload ->> 'interval_seconds' = '3600'
      AND r.valid_at > :lower_bound AND r.valid_at <= :upper_bound
      AND (r.payload -> 'values' ->> 'rain' IS NOT NULL
           OR r.payload -> 'values' ->> 'temperature_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'relative_humidity_2m' IS NOT NULL
           OR r.payload -> 'values' ->> 'wind_speed_10m' IS NOT NULL)
    ON CONFLICT (location_id, weather_source_id, hour_start_utc, snapshot_received_at)
        WHERE issued_at IS NULL
    DO UPDATE SET rainfall_mm = EXCLUDED.rainfall_mm,
                  air_temperature_c = EXCLUDED.air_temperature_c,
                  relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                  wind_speed_mps = EXCLUDED.wind_speed_mps
""")


class ForecastRepository:
    def __init__(self, settings: DatabaseSettings):
        self.engine = create_engine(
            settings.url(), poolclass=NullPool, connect_args={"connect_timeout": 5}
        )

    def materialize(self, start_date, end_date):
        with self.engine.begin() as conn:
            if not conn.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": LOCK_KEY},
            ):
                raise WarehouseBusy
            return materialize_forecast_facts(conn, start_date, end_date)


def materialize_forecast_facts(conn, start_date, end_date):
    source_id = conn.scalar(
        text("SELECT id FROM data_sources WHERE code = :code"),
        {"code": SOURCE_CODE},
    )
    if source_id is None:
        raise ValueError("No Open-Meteo forecast source has been ingested")

    bounds = conn.execute(
        BOUNDS, {"start_date": start_date, "end_date": end_date}
    ).mappings().one()
    params = dict(bounds) | {"source_id": source_id}

    unknown = conn.execute(UNKNOWN_LOCATIONS, params).scalars().all()
    if unknown:
        raise ValueError(
            "Forecast locations are missing from dim_location: " + ", ".join(unknown)
        )
    locations = conn.execute(SNAPSHOT_ROWS, params).scalars().all()
    if not locations:
        raise ValueError("No hourly forecast measurements exist in the requested range")

    conn.execute(text("""
        INSERT INTO dim_weather_source (data_source_id, name)
        VALUES (:source_id, 'Open-Meteo Forecast API (best match)')
        ON CONFLICT (data_source_id) DO NOTHING
    """), params)
    conn.execute(text("""
        INSERT INTO dim_date (local_date)
        SELECT generated_day::date
        FROM generate_series(
            CAST(:start_date AS date),
            CAST(:end_date AS date),
            INTERVAL '1 day'
        ) AS generated_day
        ON CONFLICT (local_date) DO NOTHING
    """), {"start_date": start_date, "end_date": end_date})
    conn.execute(text("""
        INSERT INTO dim_time (hour_start_utc)
        SELECT DISTINCT r.valid_at - INTERVAL '1 hour'
        FROM raw_weather_forecasts r
        WHERE r.source_id = :source_id
          AND r.payload ->> 'kind' = 'hourly'
          AND r.payload ->> 'interval_seconds' = '3600'
          AND r.valid_at > :lower_bound AND r.valid_at <= :upper_bound
        ON CONFLICT (hour_start_utc) DO NOTHING
    """), params)

    issued_rows = conn.execute(UPSERT_ISSUED, params).rowcount
    snapshot_rows = conn.execute(UPSERT_SNAPSHOTS, params).rowcount
    return {
        "start_date": start_date,
        "end_date": end_date,
        "rows_upserted": max(issued_rows, 0) + max(snapshot_rows, 0),
        "locations": locations,
    }
