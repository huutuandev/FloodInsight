from sqlalchemy import create_engine, text

from ..config import DatabaseSettings

QUERIES = {
    "rainfall_coverage": """
        SELECT l.code AS location, d.code AS source,
               min(f.local_date) AS first_date, max(f.local_date) AS last_date,
               count(*) AS days_with_rainfall
        FROM fact_rainfall_daily f
        JOIN dim_location l ON l.id = f.location_id
        JOIN dim_weather_source s ON s.id = f.weather_source_id
        JOIN data_sources d ON d.id = s.data_source_id
        WHERE (CAST(:location AS text) IS NULL OR l.code = :location)
          AND d.code = :source
        GROUP BY l.code, d.code
        ORDER BY l.code, d.code
    """,
    "locations": """
        SELECT code, name, latitude, longitude FROM dim_location
        WHERE (CAST(:location AS text) IS NULL OR code = :location)
        ORDER BY code
    """,
    "observations": """
        SELECT l.code AS location, d.code AS source, f.hour_start_utc AS valid_at,
               t.local_date, f.rainfall_mm, f.air_temperature_c, f.relative_humidity_pct,
               f.wind_speed_mps
        FROM fact_weather_hourly f JOIN dim_time t USING (hour_start_utc)
        JOIN dim_location l ON l.id = f.location_id
        JOIN dim_weather_source s ON s.id = f.weather_source_id
        JOIN data_sources d ON d.id = s.data_source_id
        WHERE (CAST(:location AS text) IS NULL OR l.code = :location)
          AND (CAST(:source AS text) IS NULL OR d.code = :source)
          AND f.hour_start_utc >= warehouse_local_day_start(:start_date)
          AND f.hour_start_utc < warehouse_local_day_start(:end_date + 1)
        ORDER BY f.hour_start_utc DESC, l.code, d.code
    """,
    "forecasts": """
        SELECT * FROM (
            SELECT DISTINCT ON (r.source_id, r.source_location_key, r.valid_at)
                   r.source_location_key AS location, d.code AS source, r.valid_at,
                   r.issued_at, r.received_at, r.payload
            FROM raw_weather_forecasts r JOIN data_sources d ON d.id = r.source_id
            WHERE (CAST(:location AS text) IS NULL OR r.source_location_key = :location)
              AND (CAST(:source AS text) IS NULL OR d.code = :source)
              AND (r.issued_at IS NOT NULL OR r.payload ->> 'kind' = 'hourly')
              AND r.valid_at >= warehouse_local_day_start(:start_date)
              AND r.valid_at < warehouse_local_day_start(:end_date + 1)
            ORDER BY r.source_id, r.source_location_key, r.valid_at,
                     coalesce(r.issued_at, r.received_at) DESC, r.received_at DESC, r.id DESC
        ) latest ORDER BY valid_at DESC, location, source
    """,
}
PERIODS = {"daily": "vw_weather_daily", "weekly": "vw_weather_weekly", "monthly": "vw_weather_monthly"}


def read_page(kind, filters, period):
    params = filters.model_dump()
    params["fetch"] = params["limit"] + 1
    if kind == "rainfall":
        view = PERIODS[period]
        query = f"""
            SELECT l.code AS location, d.code AS source, v.period_start, v.period_end,
                   v.rainfall_total_mm, v.rainfall_hours, v.loaded_hours, v.expected_hours
            FROM {view} v JOIN dim_location l ON l.id = v.location_id
            JOIN dim_weather_source s ON s.id = v.weather_source_id
            JOIN data_sources d ON d.id = s.data_source_id
            WHERE (CAST(:location AS text) IS NULL OR l.code = :location)
              AND (CAST(:source AS text) IS NULL OR d.code = :source)
              AND v.period_start <= :end_date AND v.period_end > :start_date
            ORDER BY v.period_start DESC, l.code, d.code
        """
    else:
        query = QUERIES[kind]
    engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(query + " LIMIT :fetch OFFSET :offset"), params).mappings().all()
    finally:
        engine.dispose()
    return {
        "items": [dict(row) for row in rows[:params["limit"]]],
        "has_more": len(rows) > params["limit"],
    }

