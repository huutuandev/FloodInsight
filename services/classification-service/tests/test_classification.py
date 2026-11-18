import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from floodinsight_classification.main import app
from floodinsight_classification.services.classifier import CLASSES, Thresholds, rainfall_labels
from floodinsight_ml.storage import DatabaseSettings, connect

WINDOW = {"location": "hai-chau", "start_date": "2023-06-01", "end_date": "2024-02-29"}


def test_class_thresholds_are_ordered_and_lower_inclusive():
    thresholds = Thresholds()
    assert rainfall_labels([0, 0.1, 9.99, 10, 24.99, 25], thresholds).tolist() == [0, 1, 1, 2, 2, 3]
    assert rainfall_labels([1.0], Thresholds(light_mm=2)).tolist() == [0]
    with pytest.raises(ValidationError):
        Thresholds(moderate_mm=25, heavy_mm=10)


def test_classifier_reports_support_probabilities_and_regenerates():
    if os.getenv("FLOODINSIGHT_RUN_ML_DB_TESTS") != "1":
        pytest.skip("Requires real warehouse data in a disposable database")
    assert DatabaseSettings().db == "floodinsight_ml_test"
    with TestClient(app) as client:
        response = client.post("/classification/train", json=WINDOW | {"availability": "retrospective"})
        assert response.status_code == 200, response.text
        model = response.json()
        version = model["version"]
        evaluation = client.get("/classification/metrics", params={"version": version}).json()
        assert evaluation["class_order"] == list(CLASSES)
        assert all(value > 0 for value in evaluation["splits"]["train"]["class_counts"].values())
        for name in ("validation", "test"):
            metric = evaluation["metrics"][name]
            assert sum(map(sum, metric["confusion_matrix"])) == evaluation["splits"][name]["samples"]
            assert 0 <= metric["f1_macro"] <= 1
        print("CLASSIFICATION_METRICS", evaluation["splits"], evaluation["metrics"])
        request = {"location": "hai-chau", "version": version}
        result = client.post("/classification/predict", json=request)
        assert result.status_code == 200, result.text
        predicted = result.json()
        probs = predicted["probabilities"]
        assert set(probs) == set(CLASSES)
        assert sum(probs.values()) == pytest.approx(1)
        assert probs[predicted["label"]] == pytest.approx(predicted["confidence"], abs=1e-6)
        assert client.get("/classification/results", params={"version": version}).json()
        with connect() as conn:
            conn.execute("DELETE FROM classification_results WHERE model_version_id = %s", (model["id"],))
        assert client.get("/classification/results", params={"version": version}).json() == []
        restored = client.post("/classification/predict", json=request | {"issued_at": predicted["issued_at"]})
        assert restored.json() == predicted

