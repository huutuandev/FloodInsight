from floodinsight_ml.storage import connect


def save_outlook(version_id, location, issued, today, predictions):
    with connect() as conn:
        # Serialize publication for the same point, version and local date.
        key = f"outlook:{version_id}:{location['location_id']}:{today}"
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
        existing = conn.execute("""
            SELECT 1 FROM prediction_results
            WHERE model_version_id = %s AND location_id = %s
              AND issued_at >= warehouse_local_day_start(%s)
              AND issued_at < warehouse_local_day_start(%s::date + 1)
            LIMIT 1
        """, (version_id, location["location_id"], today, today)).fetchone()
        if existing:
            return False
        for row in predictions:
            target = row["target_date"]
            conn.execute("INSERT INTO dim_date (local_date) VALUES (%s) ON CONFLICT DO NOTHING", (target,))
            instant = conn.execute(
                "SELECT warehouse_local_day_start(%s::date) AS instant", (target,)
            ).fetchone()["instant"]
            conn.execute("INSERT INTO dim_time (hour_start_utc) VALUES (%s) ON CONFLICT DO NOTHING", (instant,))
            conn.execute("""
                INSERT INTO prediction_results
                    (model_version_id, location_id, weather_source_id, target_hour_utc, issued_at, rainfall_mm)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (version_id, location["location_id"], location["weather_source_id"],
                  instant, issued, row["rainfall_mm"]))
        return True


def outlook_history(location, start, end, lead=None, *, version=None, issue_date=None, latest_per_day=False):
    distinct = "DISTINCT ON (target_date)" if latest_per_day else ""
    with connect() as conn:
        return conn.execute(f"""
            WITH outlook AS (
                SELECT m.version, p.issued_at, t.local_date AS target_date, p.rainfall_mm::float8,
                       (p.issued_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS issue_date
                FROM prediction_results p
                JOIN model_versions m ON m.id = p.model_version_id
                JOIN dim_location l ON l.id = p.location_id
                JOIN dim_time t ON t.hour_start_utc = p.target_hour_utc
                WHERE m.kind = 'prediction' AND m.model_name = 'seven-day-rainfall-regressors'
                  AND l.code = %s
                  AND p.target_hour_utc >= warehouse_local_day_start(%s)
                  AND p.target_hour_utc < warehouse_local_day_start(%s::date + 1)
            )
            SELECT {distinct} version, issued_at, target_date, rainfall_mm,
                   target_date - issue_date AS lead_days,
                   issue_date - 13 AS input_start, issue_date - 7 AS input_end
            FROM outlook
            WHERE (%s::int IS NULL OR target_date - issue_date = %s)
              AND (%s::text IS NULL OR version = %s)
              AND (%s::date IS NULL OR issue_date = %s)
            ORDER BY target_date DESC, issued_at DESC, version
            LIMIT %s
        """, (location, start, end, lead, lead, version, version, issue_date, issue_date,
              3660 if latest_per_day else 210)).fetchall()
