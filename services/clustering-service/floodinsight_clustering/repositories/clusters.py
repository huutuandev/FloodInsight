from psycopg.types.json import Jsonb

from floodinsight_ml.storage import SOURCE, connect


def daily_features(window):
    with connect() as conn:
        return conn.execute("""
            SELECT f.location_id, f.weather_source_id, l.code AS location,
                   warehouse_local_day_start(t.local_date) AS lower,
                   warehouse_local_day_start(t.local_date + 1) AS upper,
                   sum(f.rainfall_mm)::float8 AS rainfall,
                   coalesce(avg(f.rainfall_mm) FILTER (WHERE f.rainfall_mm > 0), 0)::float8 AS intensity,
                   count(*) FILTER (WHERE f.rainfall_mm > 0) AS rainy_hours,
                   avg(f.relative_humidity_pct)::float8 AS humidity,
                   avg(f.air_temperature_c)::float8 AS temperature,
                   avg(f.wind_speed_mps)::float8 AS wind
            FROM fact_weather_hourly f JOIN dim_time t USING (hour_start_utc)
            JOIN dim_location l ON l.id = f.location_id
            JOIN dim_weather_source s ON s.id = f.weather_source_id
            JOIN data_sources d ON d.id = s.data_source_id
            WHERE d.code = %s AND (%s::text IS NULL OR l.code = %s)
              AND f.hour_start_utc >= warehouse_local_day_start(%s)
              AND f.hour_start_utc < warehouse_local_day_start(%s::date + 1)
            GROUP BY f.location_id, f.weather_source_id, l.code, t.local_date
            HAVING count(f.rainfall_mm) = extract(epoch FROM warehouse_local_day_start(t.local_date + 1)
                    - warehouse_local_day_start(t.local_date)) / 3600
            ORDER BY t.local_date, l.code
        """, (SOURCE, window.location, window.location, window.start_date, window.end_date)).fetchall()


def save_assignments(model_id, rows, assignments):
    with connect() as conn, conn.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO clustering_results (model_version_id, location_id, weather_source_id,
                                            window_start_utc, window_end_utc, cluster_label, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_version_id, location_id, weather_source_id, window_start_utc, window_end_utc)
            DO UPDATE SET cluster_label = EXCLUDED.cluster_label, details = EXCLUDED.details
        """, [(model_id, row["location_id"], row["weather_source_id"], row["lower"], row["upper"],
                 label, Jsonb(details)) for row, (label, details) in zip(rows, assignments)])


def results(model_id, limit, offset, location=None, start=None, end=None):
    with connect() as conn:
        return conn.execute("""
            SELECT l.code AS location, r.window_start_utc, r.window_end_utc, r.cluster_label, r.details
            FROM clustering_results r JOIN dim_location l ON l.id = r.location_id
            WHERE r.model_version_id = %s
              AND (%s::text IS NULL OR l.code = %s)
              AND (%s::date IS NULL OR r.window_start_utc >= warehouse_local_day_start(CAST(%s AS date)))
              AND (%s::date IS NULL OR r.window_start_utc < warehouse_local_day_start(CAST(%s AS date) + 1))
            ORDER BY r.window_start_utc, l.code LIMIT %s OFFSET %s
        """, (model_id, location, location, start, start, end, end, limit, offset)).fetchall()

