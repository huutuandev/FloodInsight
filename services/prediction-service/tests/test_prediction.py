import os
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from floodinsight_ml.daily import LAGS, lag_features
from floodinsight_ml.storage import DatabaseSettings, connect
from floodinsight_prediction.main import app
from floodinsight_prediction.services.regression import climatology_predictions

WINDOW = {"location": "hai-chau", "start_date": "2023-06-01", "end_date": "2024-02-29"}


def test_climatology_is_fit_only_on_training_data():
    train = pytest.importorskip("pandas").DataFrame({
        "target_date": [date(2024, 1, 10), date(2024, 1, 20), date(2024, 2, 10)],
        "target": [1.0, 3.0, 8.0],
    })
    split = pytest.importorskip("pandas").DataFrame({
        "target_date": [date(2024, 1, 25), date(2024, 2, 25), date(2024, 3, 25)],
    })
    predicted = climatology_predictions(train, split)
    assert predicted.tolist() == [2.0, 8.0, 4.0]


def test_features_exclude_unavailable_or_missing_archive_days():
    target = date(2023, 10, 20)
    issued = datetime(2023, 10, 18, 17, tzinfo=timezone.utc)
    rows = {
        target - timedelta(days=lag): {
            "day_end": issued - timedelta(days=lag - 2), "received_at": issued + timedelta(days=1),
            "rainfall": 2.0, "temperature": 25.6, "humidity": 93.0, "wind": 1.30,
        } for lag in LAGS
    }
    assert lag_features(rows, target, issued, "recorded") is None
    assert lag_features(rows, target, issued, "retrospective")["rain_mean_d8_d14"] == 2
    rows.pop(target - timedelta(days=12))
    assert lag_features(rows, target, issued, "retrospective") is None


def test_prediction_trains_evaluates_and_regenerates():
    if os.getenv("FLOODINSIGHT_RUN_ML_DB_TESTS") != "1":
        pytest.skip("Requires real warehouse data in a disposable database")
    assert DatabaseSettings().db == "floodinsight_ml_test"
    with TestClient(app) as client:
        strict = client.post("/prediction/train", json=WINDOW)
        assert strict.status_code == 422
        response = client.post("/prediction/train", json=WINDOW | {"availability": "retrospective"})
        assert response.status_code == 200, response.text
        model = response.json()
        version = model["version"]
        metrics = client.get("/prediction/metrics", params={"version": version}).json()
        assert metrics["splits"]["train"]["last_target"] < metrics["splits"]["validation"]["first_target"]
        assert metrics["splits"]["validation"]["last_target"] < metrics["splits"]["test"]["first_target"]
        print("PREDICTION_METRICS", metrics["splits"], metrics["metrics"])
        request = {"location": "hai-chau", "version": version}
        result = client.post("/prediction/predict", json=request)
        assert result.status_code == 200, result.text
        prediction = result.json()
        assert prediction["rainfall_mm"] >= 0
        assert client.get("/prediction/results", params={"version": version}).json()
        with connect() as conn:
            conn.execute("DELETE FROM prediction_results WHERE model_version_id = %s", (model["id"],))
        assert client.get("/prediction/results", params={"version": version}).json() == []
        regenerated = client.post("/prediction/predict", json=request | {"issued_at": prediction["issued_at"]})
        assert regenerated.json() == prediction

