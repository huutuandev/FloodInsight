from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel

from .schemas import Location, Version, Window
from .storage import DataUnavailable, SOURCE, connect

DAY = timedelta(days=1)
# Allow the ERA5 publication delay before using a daily total as a feature.
LAGS = range(8, 15)
DELAY = timedelta(days=6)
FEATURES = [
    "rain_d8", "rain_d9", "rain_d10", "rain_mean_d8_d14",
    "temperature_d8", "humidity_d8", "wind_d8", "season_sin", "season_cos",
]


class DailyTraining(Window):
    availability: Literal["recorded", "retrospective"] = "recorded"


class NextDayRequest(BaseModel):
    location: Location
    version: Version | None = None
    issued_at: AwareDatetime | None = None


def daily_rows(start, end, location):
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
            )
            SELECT e.location_id, e.weather_source_id, e.location, e.day,
                   warehouse_local_day_start(e.day + 1) AS day_end,
                   warehouse_local_day_start(e.day) - interval '12 hours' AS nominal_issue,
                   e.rainfall, e.temperature, e.humidity, e.wind, e.received_at
            FROM era5 e
            WHERE e.obs_count = e.expected_hours
            ORDER BY e.day, e.location
        """, (SOURCE, location, location, start, end)).fetchall()


def available_at(row, mode):
    if mode == "retrospective":
        return row["day_end"] + DELAY
    receipt = row["received_at"]
    return max(row["day_end"], receipt) if receipt is not None else None


def lag_features(days, target, issued_at, mode, lead_days=1):
    lags = []
    for lag in LAGS:
        row = days.get(target - (lag + lead_days - 1) * DAY)
        if row is None or row["rainfall"] is None:
            return None
        effective = available_at(row, mode)
        if effective is None or effective > issued_at:
            return None
        lags.append(row)

    d8 = lags[0]
    angle = 2 * np.pi * (target.timetuple().tm_yday - 1) / 366
    return dict(zip(FEATURES, (
        d8["rainfall"], lags[1]["rainfall"], lags[2]["rainfall"],
        float(np.mean([row["rainfall"] for row in lags])),
        d8["temperature"], d8["humidity"], d8["wind"],
        float(np.sin(angle)), float(np.cos(angle)),
    )))


def training_partitions(window, lead_days=1, rows=None):
    if rows is None:
        rows = daily_rows(window.start_date - (14 + lead_days - 1) * DAY, window.end_date, window.location)
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
        issue = row["nominal_issue"] - (lead_days - 1) * DAY
        features = lag_features(
            by_location[row["location"]], day, issue,
            window.availability, lead_days,
        )
        if features is not None:
            examples.append(features | {
                "location": row["location"], "target_date": day, "target": row["rainfall"],
                "issue": issue, "label_available": label_available,
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
    if model["training_metadata"].get("features") != FEATURES:
        raise DataUnavailable("Retrain this model with the current rainfall features")
    now = datetime.now(timezone.utc)
    issued = (payload.issued_at or now).astimezone(timezone.utc)
    if issued > now or issued < model["created_at"]:
        raise DataUnavailable("Issue time must fall between model creation and the present")
    if payload.location not in model["training_metadata"]["locations"]:
        raise DataUnavailable("This model has no training data for the requested location")
    with connect() as conn:
        calendar = conn.execute("""
            SELECT (%s::timestamptz AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + 1 AS target
        """, (issued,)).fetchone()
    target = calendar["target"]
    history = daily_rows(target - max(LAGS) * DAY, target - min(LAGS) * DAY, payload.location)
    features = lag_features(
        {row["day"]: row for row in history}, target, issued, "recorded",
    )
    if features is None:
        raise DataUnavailable("Required ERA5 lag days (d8-d14) must have been received by issuance")
    return target, issued, history[-1] if history else None, pd.DataFrame([features], columns=FEATURES).astype(float)

