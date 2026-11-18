from psycopg.types.json import Jsonb

from .storage import connect


def save_next_day(kind, version_id, target, issued, location, value, probabilities=None):
    with connect() as conn:
        conn.execute("INSERT INTO dim_date (local_date) VALUES (%s) ON CONFLICT DO NOTHING", (target,))
        instant = conn.execute(
            "SELECT warehouse_local_day_start(%s) AS instant", (target,)
        ).fetchone()["instant"]
        conn.execute("INSERT INTO dim_time (hour_start_utc) VALUES (%s) ON CONFLICT DO NOTHING", (instant,))
        key = (version_id, location["location_id"], location["weather_source_id"], instant, issued)
        if kind == "prediction":
            row = conn.execute("""
                INSERT INTO prediction_results
                    (model_version_id, location_id, weather_source_id, target_hour_utc, issued_at, rainfall_mm)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_version_id, location_id, weather_source_id, target_hour_utc, issued_at)
                DO UPDATE SET rainfall_mm = EXCLUDED.rainfall_mm
                RETURNING rainfall_mm::float8
            """, (*key, value)).fetchone()
        else:
            row = conn.execute("""
                INSERT INTO classification_results
                    (model_version_id, location_id, weather_source_id, target_hour_utc, issued_at,
                     label, confidence, probabilities)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_version_id, location_id, weather_source_id, target_hour_utc, issued_at)
                DO UPDATE SET label = EXCLUDED.label, confidence = EXCLUDED.confidence,
                              probabilities = EXCLUDED.probabilities
                RETURNING label, confidence::float8, probabilities
            """, (*key, value, probabilities[value], Jsonb(probabilities))).fetchone()
    return row | {"target_date": target, "issued_at": issued, "location": location["location"]}


def next_day_results(kind, version_id, limit, offset, location=None, start=None, end=None):
    if kind == "prediction":
        table, columns = "prediction_results", "r.rainfall_mm::float8"
    else:
        table, columns = "classification_results", "r.label, r.confidence::float8, r.probabilities"
    with connect() as conn:
        return conn.execute(f"""
            SELECT l.code AS location, t.local_date AS target_date, r.issued_at, {columns}
            FROM {table} r JOIN dim_location l ON l.id = r.location_id
            JOIN dim_time t ON t.hour_start_utc = r.target_hour_utc
            WHERE r.model_version_id = %s
              AND (%s::text IS NULL OR l.code = %s)
              AND (%s::date IS NULL OR t.local_date >= %s)
              AND (%s::date IS NULL OR t.local_date <= %s)
            ORDER BY r.target_hour_utc DESC, r.issued_at DESC, l.code
            LIMIT %s OFFSET %s
        """, (version_id, location, location, start, start, end, end, limit, offset)).fetchall()

