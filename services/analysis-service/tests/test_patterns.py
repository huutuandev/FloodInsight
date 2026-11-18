import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from floodinsight_analysis.services.patterns import calculate_patterns

FIXTURE_NAME = "open_meteo_era5_hai_chau_2023-10-13.json"
DAY = date(2023, 10, 13)


@pytest.fixture
def real_hours():
    fixture = Path(__file__).with_name(FIXTURE_NAME)
    if not fixture.exists():
        fixture = Path(__file__).parents[2] / "warehouse-service" / "tests" / "fixtures" / FIXTURE_NAME
    hours = json.loads(fixture.read_bytes())["hourly"]
    return pd.DataFrame({
        "local_date": [DAY] * 24,
        "rainfall_mm": hours["rain"][18:42],
        "relative_humidity_pct": hours["relative_humidity_2m"][17:41],
        "air_temperature_c": hours["temperature_2m"][17:41],
        "wind_speed_mps": hours["wind_speed_10m"][17:41],
        "total_precipitation_mm": hours["precipitation"][18:42],
    })


def patterns_for(hours):
    days = pd.DataFrame({
        "local_date": [DAY, date(2023, 10, 14), date(2023, 10, 15), date(2023, 10, 16)],
        "expected_hours": [24, 24, 24, 24],
    })
    return {result.name: result for result in calculate_patterns(hours, days)}


def test_real_daily_weekly_monthly_resampling_and_gaps(real_hours):
    results = patterns_for(real_hours)
    daily = results["rainfall_daily"]
    daily_rows = daily.option["dataset"]["source"]
    assert daily_rows[0][1] == pytest.approx(73.6)
    assert daily_rows[1:] == [
        ["2023-10-14", None], ["2023-10-15", None], ["2023-10-16", None],
    ]
    assert daily.metadata["coverage"][0]["complete_period"] is True
    weekly = results["rainfall_weekly"]
    assert weekly.option["dataset"]["source"][0] == ["2023-10-09", pytest.approx(73.6)]
    assert weekly.option["dataset"]["source"][1] == ["2023-10-16", None]
    assert weekly.metadata["coverage"][0]["complete_period"] is False
    assert results["rainfall_monthly"].option["dataset"]["source"] == [
        ["2023-10-01", pytest.approx(73.6)]
    ]
    assert results["monthly_trend"].metadata["slope_mm_per_month"] is None
    assert results["monthly_seasonality"].status == "insufficient_data"


def test_pairs_histogram_and_descriptive_statistics(real_hours):
    real_hours.loc[0, "relative_humidity_pct"] = np.nan
    patterns = patterns_for(real_hours)
    assert patterns["rainfall_vs_humidity"].metadata["paired_hours"] == 23
    assert patterns["rainfall_vs_temperature"].metadata["paired_hours"] == 24
    assert sum(b["hours"] for b in patterns["rainfall_histogram"].metadata["bins"]) == 24
    matrix = patterns["correlation"].metadata
    assert matrix["pair_counts"][0][1] == 23
    assert "total_precipitation_mm" in matrix["variables"]
    pairs = real_hours.iloc[1:][["rainfall_mm", "relative_humidity_pct"]].to_numpy()
    assert matrix["matrix"][0][1] == pytest.approx(np.corrcoef(pairs.T)[0, 1])
    rainfall = patterns["descriptive_statistics"].option["dataset"]["source"][0]
    assert rainfall == [
        "rainfall_mm", 24, real_hours.rainfall_mm.min(), real_hours.rainfall_mm.max(),
        pytest.approx(73.6 / 24), real_hours.rainfall_mm.median(),
        pytest.approx(np.std(real_hours.rainfall_mm, ddof=1)),
    ]


def test_empty_and_single_sample_produce_json_nulls(real_hours):
    for frame in (real_hours.iloc[:0], real_hours.iloc[:1]):
        output = patterns_for(frame)
        assert len(output) == 10
        assert output["correlation"].status == "insufficient_data"
        stats = output["descriptive_statistics"].option["dataset"]["source"][0]
        assert stats[-1] is None
        json.dumps([p.model_dump(mode="json") for p in output.values()], allow_nan=False)

