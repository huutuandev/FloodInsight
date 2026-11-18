import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from floodinsight_analysis.config import DatabaseSettings
from floodinsight_analysis.main import app
from floodinsight_analysis.repositories.patterns import KEY_PREFIX, connect

SCOPE = {
    "location": "hai-chau",
    "source": "open-meteo-archive-era5",
    "start_date": "2022-10-01",
    "end_date": "2023-11-30",
}


def test_real_trend_seasonality_and_regeneration():
    if os.getenv("FLOODINSIGHT_RUN_ANALYSIS_DB_TESTS") != "1":
        pytest.skip("Requires a disposable database with documented ERA5 backfill.")
    if DatabaseSettings().db != "floodinsight_analysis_test":
        pytest.fail("Use only the floodinsight_analysis_test database.")
    with connect() as conn:
        monthly = conn.execute("""
            SELECT period_start, rainfall_total_mm FROM vw_weather_monthly v
            JOIN dim_location l ON l.id = v.location_id
            JOIN dim_weather_source w ON w.id = v.weather_source_id
            JOIN data_sources d ON d.id = w.data_source_id
            WHERE l.code = %s AND d.code = %s AND expected_hours = rainfall_hours
              AND period_start BETWEEN %s::date AND %s::date ORDER BY period_start
        """, tuple(SCOPE.values())).fetchall()
        assert [str(row["period_start"]) for row in monthly] == ["2022-10-01", "2023-10-01", "2023-11-01"]
        totals = [float(row["rainfall_total_mm"]) for row in monthly]

    with TestClient(app) as client:
        response = client.post("/analysis/generate", json=SCOPE)
        assert response.status_code == 200, response.text
        original = {p["name"]: p for p in response.json()}
        assert len(original) == 10
        assert all(p["status"] == "ready" for p in original.values())
        trend = original["monthly_trend"]["metadata"]
        slope = np.linalg.lstsq([[0, 1], [12, 1], [13, 1]], totals, rcond=None)[0][0]
        assert trend["complete_months"] == 3
        assert trend["slope_mm_per_month"] == pytest.approx(slope)
        seasonality = original["monthly_seasonality"]
        assert seasonality["metadata"]["complete_month_counts"][9:11] == [2, 1]
        assert seasonality["option"]["dataset"]["source"][9] == [
            "Oct", pytest.approx((totals[0] + totals[1]) / 2),
        ]
        pattern_filter = SCOPE | {"pattern": "monthly_seasonality"}
        assert client.get("/analysis/patterns", params=pattern_filter).json() == [seasonality]

        with connect() as conn:
            counts_sql = """
                SELECT (SELECT count(*) FROM raw_weather_observations) AS raw,
                       (SELECT count(*) FROM fact_weather_hourly) AS hourly,
                       (SELECT count(*) FROM fact_rainfall_daily) AS daily,
                       (SELECT count(*) FROM model_versions) AS models
            """
            counts_before = conn.execute(counts_sql).fetchone()
            removed = conn.execute(
                """
                DELETE FROM analysis_results a
                USING dim_location l, dim_weather_source w, data_sources d
                WHERE starts_with(a.analysis_key, %s) AND a.location_id = l.id
                  AND a.weather_source_id = w.id AND w.data_source_id = d.id
                  AND l.code = %s AND d.code = %s
                  AND a.window_start_utc = warehouse_local_day_start(%s::date)
                  AND a.window_end_utc = warehouse_local_day_start(%s::date + 1)
                """, (KEY_PREFIX, *SCOPE.values()),
            )
            assert removed.rowcount == 10

        assert client.get("/analysis/patterns", params=SCOPE).json() == []
        restored = client.post("/analysis/generate", json=SCOPE)
        assert restored.status_code == 200, restored.text
        stored = client.get("/analysis/patterns", params=SCOPE)
        assert stored.json() == restored.json()
        for item in stored.json():
            previous = original[item["name"]].copy()
            assert item.pop("generated_at") != previous.pop("generated_at")
            assert item == previous

        empty_window = SCOPE | {"start_date": "2022-11-01", "end_date": "2022-11-02"}
        no_data = client.post("/analysis/generate", json=empty_window)
        assert no_data.status_code == 200, no_data.text
        assert all(p["status"] == "insufficient_data" for p in no_data.json())
        with connect() as conn:
            assert conn.execute(counts_sql).fetchone() == counts_before

