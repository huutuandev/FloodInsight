from contextlib import contextmanager

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..config import DatabaseSettings
from ..schemas.patterns import PatternScope, StoredPattern
from ..services.patterns import CORE_COLUMNS, calculate_patterns

KEY_PREFIX = "timeseries:v1:"
EXTRA_COLUMN = "total_precipitation_mm"


class ScopeNotFound(Exception):
    pass


@contextmanager
def connect():
    config = DatabaseSettings()
    with psycopg.connect(
        host=config.host, port=config.port, dbname=config.db, user=config.user,
        password=config.password.get_secret_value(), connect_timeout=5,
        options="-c timezone=UTC -c statement_timeout=30000", row_factory=dict_row,
    ) as conn:
        yield conn


def resolve_scope(conn, scope: PatternScope):
    row = conn.execute("""
        SELECT l.id AS location_id, w.id AS weather_source_id, d.id AS data_source_id,
               warehouse_local_day_start(%s::date) AS lower,
               warehouse_local_day_start(%s::date + 1) AS upper
        FROM dim_location l CROSS JOIN dim_weather_source w
        JOIN data_sources d ON d.id = w.data_source_id
        WHERE l.code = %s AND d.code = %s
    """, (scope.start_date, scope.end_date, scope.location, scope.source)).fetchone()
    if row is None:
        raise ScopeNotFound
    return row


def read_inputs(conn, scope, keys):
    calendar = conn.execute("""
        SELECT day AS local_date,
               extract(epoch FROM warehouse_local_day_start(day + 1)
                                - warehouse_local_day_start(day)) / 3600 AS expected_hours
        FROM (
            SELECT %s::date + n AS day FROM generate_series(0, %s::date - %s::date) AS n
        ) days
        ORDER BY day
    """, (scope.start_date, scope.end_date, scope.start_date)).fetchall()
    rows = conn.execute("""
        SELECT t.local_date, f.rainfall_mm, f.relative_humidity_pct,
               f.air_temperature_c, f.wind_speed_mps,
               CASE WHEN jsonb_typeof(r.payload -> 'values' -> 'precipitation') = 'number'
                    THEN (r.payload -> 'values' ->> 'precipitation')::numeric
               END AS total_precipitation_mm
        FROM fact_weather_hourly f JOIN dim_time t USING (hour_start_utc)
        LEFT JOIN raw_weather_observations r ON %(source)s = 'open-meteo-archive-era5'
             AND r.source_id = %(data_source_id)s
             AND r.source_location_key = %(location)s
             AND r.valid_at = f.hour_start_utc + INTERVAL '1 hour'
        WHERE f.location_id = %(location_id)s AND f.weather_source_id = %(weather_source_id)s
          AND f.hour_start_utc >= %(lower)s AND f.hour_start_utc < %(upper)s
        ORDER BY f.hour_start_utc
    """, keys | {"source": scope.source, "location": scope.location}).fetchall()
    hours = pd.DataFrame.from_records(rows, columns=["local_date", *CORE_COLUMNS, EXTRA_COLUMN])
    days = pd.DataFrame.from_records(calendar)
    days["expected_hours"] = days["expected_hours"].astype(int)
    # Total precipitation is optional and must be physically nonnegative.
    hours[EXTRA_COLUMN] = pd.to_numeric(hours[EXTRA_COLUMN], errors="coerce")
    hours[EXTRA_COLUMN] = hours[EXTRA_COLUMN].where(hours[EXTRA_COLUMN] >= 0)
    return hours, days


def get_results(conn, keys, name=None):
    rows = conn.execute("""
        SELECT result, created_at FROM analysis_results
        WHERE location_id = %(location_id)s AND weather_source_id = %(weather_source_id)s
          AND window_start_utc = %(lower)s AND window_end_utc = %(upper)s
          AND starts_with(analysis_key, %(prefix)s)
          AND (%(key)s::text IS NULL OR analysis_key = %(key)s)
        ORDER BY analysis_key
    """, keys | {"prefix": KEY_PREFIX, "key": KEY_PREFIX + name if name else None}).fetchall()
    return [StoredPattern.model_validate(row["result"] | {"generated_at": row["created_at"]})
            for row in rows]


def retrieve(scope: PatternScope, name=None):
    with connect() as conn:
        return get_results(conn, resolve_scope(conn, scope), name)


def regenerate(scope: PatternScope):
    with connect() as conn:
        keys = resolve_scope(conn, scope)
        lock_id = f"{KEY_PREFIX}{keys['location_id']}:{keys['weather_source_id']}:{keys['lower']}:{keys['upper']}"
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_id,))
        hours, days = read_inputs(conn, scope, keys)
        patterns = calculate_patterns(hours, days)
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO analysis_results
                    (analysis_key, location_id, weather_source_id, window_start_utc,
                     window_end_utc, result, created_at)
                VALUES (%(key)s, %(location_id)s, %(weather_source_id)s, %(lower)s,
                        %(upper)s, %(result)s, clock_timestamp())
                ON CONFLICT (analysis_key, location_id, weather_source_id, window_start_utc, window_end_utc)
                DO UPDATE SET result = EXCLUDED.result, created_at = EXCLUDED.created_at
            """, [
                keys | {"key": KEY_PREFIX + p.name, "result": Jsonb(p.model_dump(mode="json"))}
                for p in patterns
            ])
        return get_results(conn, keys)

