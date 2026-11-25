from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text

from ..repositories.historical import SOURCE_CODE

HOUR = timedelta(hours=1)
FRAME_COLUMNS = ["location_id", "weather_source_id", "hour_start_utc", "rainfall_mm", "received_at"]


def read_rainfall(engine, start: datetime, end: datetime) -> pd.DataFrame:
    """Read only historical rainfall and its recorded archive-availability timestamp."""
    query = text("""
        SELECT w.location_id, w.weather_source_id, w.hour_start_utc, w.rainfall_mm, r.received_at
        FROM fact_weather_hourly w
        JOIN dim_location l ON l.id = w.location_id
        JOIN dim_weather_source s ON s.id = w.weather_source_id
        JOIN data_sources d ON d.id = s.data_source_id
        JOIN raw_weather_observations r ON r.source_id = d.id
            AND r.source_location_key = l.code
            AND r.valid_at = w.hour_start_utc + INTERVAL '1 hour'
        WHERE d.code = :source AND w.hour_start_utc >= :start AND w.hour_start_utc < :end
        ORDER BY w.hour_start_utc, w.location_id, w.weather_source_id
    """)
    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
        raise ValueError("Expected an increasing range of timezone-aware instants")
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"source": SOURCE_CODE, "start": start, "end": end})


def chronological_rainfall_splits(
    rows: pd.DataFrame, cutoff: datetime, *, lookback_hours: int = 3, horizon_hours: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use exact, available lags and an embargo for labels crossing the split."""
    if cutoff.utcoffset() is None or lookback_hours < 1 or horizon_hours < 0:
        raise ValueError("Use a timezone-aware cutoff, positive lookback and nonnegative horizon")
    features = [f"rainfall_lag_{i}h" for i in range(1, lookback_hours + 1)]
    columns = ["location_id", "weather_source_id", "issue_at", "target_hour_utc", *features,
               "target_rainfall_mm"]
    train, test = [], []
    for (location, source), group in rows[FRAME_COLUMNS].groupby(["location_id", "weather_source_id"]):
        by_hour = group.set_index("hour_start_utc", verify_integrity=True)[["rainfall_mm", "received_at"]]
        hours = {hour: (value, received) for hour, value, received in by_hour.itertuples()}
        for issue in sorted(hours):
            target = issue + horizon_hours * HOUR
            target_value, target_received = hours.get(target, (None, None))
            if pd.isna(target_value):
                continue
            lags = [hours.get(issue - i * HOUR, (None, None)) for i in range(1, lookback_hours + 1)]
            if any(pd.isna(value) or pd.isna(received) or received > issue for value, received in lags):
                continue
            row = [location, source, issue, target, *(value for value, _ in lags), target_value]
            if target + HOUR <= cutoff and pd.notna(target_received) and target_received <= cutoff:
                train.append(row)
            elif issue >= cutoff:
                test.append(row)
    return (
        pd.DataFrame(train, columns=columns).sort_values("issue_at", ignore_index=True),
        pd.DataFrame(test, columns=columns).sort_values("issue_at", ignore_index=True),
    )

