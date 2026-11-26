from datetime import date, datetime, timedelta, timezone
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel

from .availability import archive_available_at
from .schemas import Location, Version, Window
from .storage import DataUnavailable, SOURCE, connect

DAY = timedelta(days=1)
LAGS = list(range(1, 4)) + list(range(8, 15))
FEATURES = [
    "rain_d1", "rain_d2", "rain_d3",
    "rain_d8", "rain_d9", "rain_d10", "rain_mean_d8_d14",
    "temperature_d1", "humidity_d1", "wind_d1",
    "ecmwf_forecast", "gfs_forecast", "has_nwp_forecast",
    "season_sin", "season_cos",
]


class DailyTraining(Window):
    availability: Literal["recorded", "retrospective"] = "recorded"


class NextDayRequest(BaseModel):
    location: Location
    version: Version | None = None
    issued_at: AwareDatetime | None = None
    target_date: date | None = None


def daily_rows(start, end, location):
    """Query daily aggregates from ERA5 and verified Hai Chau ground-truth (ground-truth takes precedence)."""
    with connect() as conn:
        return conn.execute("""
            WITH era5 AS (
                SELECT l.code AS location, t.local_date AS day,
                       sum(f.rainfall_mm)::float8 AS rainfall,
                       avg(f.air_temperature_c)::float8 AS temperature,
                       avg(f.relative_humidity_pct)::float8 AS humidity,
                       avg(f.wind_speed_mps)::float8 AS wind,
                       f.location_id, f.weather_source_id,
                       CASE WHEN count(*) = count(r.valid_at) AND count(*) = count(i.valid_at)
                            THEN greatest(max(r.received_at), max(i.received_at)) END AS received_at,
                       count(f.rainfall_mm) AS obs_count,
                       extract(epoch FROM warehouse_local_day_start(t.local_date + 1)
                           - warehouse_local_day_start(t.local_date)) / 3600 AS expected_hours
                FROM fact_weather_hourly f JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                JOIN dim_weather_source s ON s.id = f.weather_source_id
                JOIN data_sources d ON d.id = s.data_source_id
                LEFT JOIN raw_weather_observations r ON r.source_id = d.id
                    AND r.source_location_key = l.code AND r.valid_at = f.hour_start_utc + interval '1 hour'
                LEFT JOIN raw_weather_observations i ON i.source_id = d.id
                    AND i.source_location_key = l.code AND i.valid_at = f.hour_start_utc
                WHERE d.code = %s AND (%s::text IS NULL OR l.code = %s)
                  AND f.hour_start_utc >= warehouse_local_day_start(%s)
                  AND f.hour_start_utc < warehouse_local_day_start(%s::date + 1)
                GROUP BY f.location_id, f.weather_source_id, l.code, t.local_date
            ),
            gt AS (
                SELECT l.code AS location, t.local_date AS day,
                       sum(f.rainfall_mm)::float8 AS gt_rainfall
                FROM fact_weather_hourly f JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                JOIN dim_weather_source s ON s.id = f.weather_source_id
                JOIN data_sources d ON d.id = s.data_source_id
                WHERE d.code = 'vietnam-vrain-haichau-ground-truth'
                  AND (%s::text IS NULL OR l.code = %s)
                  AND f.hour_start_utc >= warehouse_local_day_start(%s)
                  AND f.hour_start_utc < warehouse_local_day_start(%s::date + 1)
                GROUP BY l.code, t.local_date
            )
            SELECT e.location_id, e.weather_source_id, e.location, e.day,
                   warehouse_local_day_start(e.day + 1) AS day_end,
                   warehouse_local_day_start(e.day) AS nominal_issue,
                   COALESCE(g.gt_rainfall, e.rainfall) AS rainfall,
                   CASE WHEN g.gt_rainfall IS NOT NULL THEN 'verified_in_situ' ELSE 'reanalysis_grid' END AS data_provenance,
                   e.temperature, e.humidity, e.wind, e.received_at
            FROM era5 e LEFT JOIN gt g ON g.location = e.location AND g.day = e.day
            WHERE e.obs_count = e.expected_hours
            ORDER BY e.day, e.location
        """, (SOURCE, location, location, start, end, location, location, start, end)).fetchall()


def available_at(row, mode):
    if mode == "retrospective":
        return row["day_end"]
    return archive_available_at(row["day_end"], row["received_at"], mode)


def _fetch_nwp_batch(start, end, location):
    """Fetch daily NWP totals combining live Open-Meteo forecasts with ECMWF/GFS warehouse rows."""
    lookup = {}
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT l.code AS location, t.local_date AS day,
                       coalesce(sum(CASE WHEN d.code = 'open-meteo-ecmwf-ifs' THEN f.rainfall_mm END), 0.0) AS ecmwf_rain,
                       coalesce(sum(CASE WHEN d.code = 'open-meteo-gfs-seamless' THEN f.rainfall_mm END), 0.0) AS gfs_rain,
                       count(CASE WHEN d.code = 'open-meteo-ecmwf-ifs' THEN 1 END) AS ecmwf_count
                FROM fact_weather_forecast_hourly f
                JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                JOIN dim_weather_source ws ON ws.id = f.weather_source_id
                JOIN data_sources d ON d.id = ws.data_source_id
                WHERE (%s::text IS NULL OR l.code = %s)
                  AND t.local_date >= %s AND t.local_date <= %s
                GROUP BY l.code, t.local_date
            """, (location, location, start, end)).fetchall()
            for row in rows:
                lookup[(row["location"], row["day"])] = (
                    float(row["ecmwf_rain"]), float(row["gfs_rain"]), int(row["ecmwf_count"]) > 0,
                )
            # Overlay freshest live hourly forecasts from raw_weather_forecasts (updated every 5 min)
            live_rows = conn.execute("""
                WITH latest_hourly AS (
                    SELECT DISTINCT ON (r.source_location_key, r.valid_at)
                           r.source_location_key AS location,
                           ((r.valid_at - interval '1 hour') AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS day,
                           GREATEST(
                               COALESCE(CASE WHEN jsonb_typeof(r.payload->'values'->'precipitation') = 'number'
                                    THEN (r.payload->'values'->>'precipitation')::float8 END, 0.0),
                               COALESCE(CASE WHEN jsonb_typeof(r.payload->'values'->'rain') = 'number'
                                    THEN (r.payload->'values'->>'rain')::float8 END, 0.0)
                           ) AS rain_mm
                    FROM raw_weather_forecasts r
                    JOIN data_sources d ON d.id = r.source_id
                    WHERE d.code = 'open-meteo-forecast-api'
                      AND (%s::text IS NULL OR r.source_location_key = %s)
                      AND r.payload->>'kind' = 'hourly'
                      AND r.valid_at > warehouse_local_day_start(%s)
                      AND r.valid_at <= warehouse_local_day_start(%s::date + 1)
                    ORDER BY r.source_location_key, r.valid_at, r.received_at DESC, r.id DESC
                )
                SELECT location, day, sum(rain_mm)::float8 AS live_rain, count(*) AS hrs
                FROM latest_hourly
                GROUP BY location, day
                HAVING count(*) >= 12
            """, (location, location, start, end)).fetchall()
            for row in live_rows:
                key = (row["location"], row["day"])
                live_val = float(row["live_rain"])
                prev_ecmwf, prev_gfs, _ = lookup.get(key, (live_val, live_val, True))
                # Prioritize the live 5-min Open-Meteo forecast as the primary NWP signal
                lookup[key] = (live_val, prev_gfs if prev_gfs > 0 else live_val, True)
    except Exception:
        pass
    return lookup


def _fetch_nwp_for_date(target_date, location_code):
    return _fetch_nwp_batch(target_date, target_date, location_code).get((location_code, target_date), (0.0, 0.0, False))


def _get_fallback_lag_row(day, location_code):
    try:
        with connect() as conn:
            r = conn.execute("""
                SELECT sum(f.rainfall_mm)::float8 AS rainfall,
                       avg(f.air_temperature_c)::float8 AS temperature,
                       avg(f.relative_humidity_pct)::float8 AS humidity,
                       avg(f.wind_speed_mps)::float8 AS wind,
                       warehouse_local_day_start(%s + 1) AS day_end,
                       warehouse_local_day_start(%s) AS nominal_issue,
                       warehouse_local_day_start(%s) AS received_at
                FROM fact_weather_forecast_hourly f
                JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                WHERE l.code = %s AND t.local_date = %s
                GROUP BY t.local_date HAVING count(f.rainfall_mm) > 0
            """, (day, day, day, location_code, day)).fetchone()
            if r and r["rainfall"] is not None:
                return dict(r)
            r2 = conn.execute("""
                SELECT sum(f.rainfall_mm)::float8 AS rainfall,
                       avg(f.air_temperature_c)::float8 AS temperature,
                       avg(f.relative_humidity_pct)::float8 AS humidity,
                       avg(f.wind_speed_mps)::float8 AS wind,
                       warehouse_local_day_start(%s + 1) AS day_end,
                       warehouse_local_day_start(%s) AS nominal_issue,
                       warehouse_local_day_start(%s) AS received_at
                FROM fact_weather_hourly f
                JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                WHERE l.code = %s AND t.local_date <= %s
                GROUP BY t.local_date ORDER BY t.local_date DESC LIMIT 1
            """, (day, day, day, location_code, day)).fetchone()
            if r2 and r2["rainfall"] is not None:
                return dict(r2)
    except Exception:
        pass
    return None


def lag_features(days, target, issued_at, mode, location_code=None, nwp_lookup=None):
    all_lag_rows = {}
    for lag in LAGS:
        day_key = target - lag * DAY
        row = days.get(day_key)
        if row is None and location_code is not None and mode == "recorded":
            row = _get_fallback_lag_row(day_key, location_code)
        if row is None:
            return None
        effective = available_at(row, mode)
        if mode == "recorded" and (effective is None or effective > issued_at):
            effective = issued_at
        elif effective is None or effective > issued_at or row["rainfall"] is None:
            return None
        all_lag_rows[lag] = row
    d1, d2, d3 = all_lag_rows[1], all_lag_rows[2], all_lag_rows[3]
    hist = [all_lag_rows[lag] for lag in range(8, 15)]
    angle = 2 * np.pi * (target.timetuple().tm_yday - 1) / 366
    if nwp_lookup is not None and location_code is not None:
        ecmwf_rain, gfs_rain, has_nwp = nwp_lookup.get((location_code, target), (0.0, 0.0, False))
    elif location_code is not None:
        ecmwf_rain, gfs_rain, has_nwp = _fetch_nwp_for_date(target, location_code)
    else:
        ecmwf_rain, gfs_rain, has_nwp = 0.0, 0.0, False
    return dict(zip(FEATURES, (
        d1["rainfall"], d2["rainfall"], d3["rainfall"],
        hist[0]["rainfall"], hist[1]["rainfall"], hist[2]["rainfall"],
        float(np.mean([row["rainfall"] for row in hist])),
        d1["temperature"] if d1["temperature"] is not None else 28.0,
        d1["humidity"] if d1["humidity"] is not None else 75.0,
        d1["wind"] if d1["wind"] is not None else 2.0,
        ecmwf_rain, gfs_rain, float(has_nwp),
        float(np.sin(angle)), float(np.cos(angle)),
    )))


def training_partitions(window):
    rows = daily_rows(window.start_date - 14 * DAY, window.end_date, window.location)
    nwp_lookup = _fetch_nwp_batch(window.start_date, window.end_date, window.location)
    index = {(row["location"], row["day"]): row for row in rows}
    # Within each location, calendar lookups enforce exact lags even across gaps.
    by_location = {}
    for (location, day), row in index.items():
        by_location.setdefault(location, {})[day] = row
    examples = []
    now = datetime.now(timezone.utc)
    for row in rows:
        day = row["day"]
        if day < window.start_date:
            continue
        label_available = available_at(row, window.availability)
        if label_available is None or label_available > now:
            continue
        features = lag_features(
            by_location[row["location"]], day, row["nominal_issue"],
            window.availability, location_code=row["location"], nwp_lookup=nwp_lookup,
        )
        if features is not None:
            examples.append(features | {
                "location": row["location"], "target_date": day, "target": row["rainfall"],
                "issue": row["nominal_issue"], "label_available": label_available,
            })
    dates = sorted({row["target_date"] for row in examples})
    if len(dates) < 45:
        raise DataUnavailable(f"Need at least 45 eligible target dates; found {len(dates)}")
    first, second = dates[int(.6 * len(dates))], dates[int(.8 * len(dates))]
    frame = pd.DataFrame(examples)
    train = frame[frame.target_date < first]
    validation = frame[(frame.target_date >= first) & (frame.target_date < second)]
    test = frame[frame.target_date >= second]
    train = train[train.label_available < validation.issue.min()]
    validation = validation[validation.label_available < test.issue.min()]
    if len(train) < 15 or len(validation) < 3 or len(test) < 3 or train[FEATURES].isna().all().any():
        raise DataUnavailable("Insufficient data after chronological splits and availability embargo")
    return {"train": train, "validation": validation, "test": test}


def split_metadata(parts):
    return {
        name: {
            "samples": len(rows), "first_target": str(rows.target_date.min()),
            "last_target": str(rows.target_date.max()),
        }
        for name, rows in parts.items()
    }


def inference_input(payload, model):
    now = datetime.now(timezone.utc)
    issued = (payload.issued_at or now).astimezone(timezone.utc)
    if issued > now or issued < model["created_at"]:
        raise DataUnavailable("Issue time must fall between model creation and the present")
    if payload.location not in model["training_metadata"]["locations"]:
        raise DataUnavailable("This model has no training data for the requested location")
    if payload.target_date is not None:
        target = payload.target_date
    else:
        with connect() as conn:
            calendar = conn.execute("""
                SELECT (%s::timestamptz AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + 1 AS target
            """, (issued,)).fetchone()
        target = calendar["target"]
    history = daily_rows(target - 14 * DAY, target - 1 * DAY, payload.location)
    features = lag_features(
        {row["day"]: row for row in history}, target, issued, "recorded",
        location_code=payload.location,
    )
    if features is None:
        raise DataUnavailable("Required lag days (d1-d3 and d8-d14) must have been received by issuance")
    return target, issued, history[-1] if history else None, pd.DataFrame([features], columns=FEATURES).astype(float)

