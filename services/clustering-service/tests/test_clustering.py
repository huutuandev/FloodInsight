import os

import pytest
from fastapi.testclient import TestClient

from floodinsight_clustering.main import app
from floodinsight_clustering.services.clusters import train_clusters
from floodinsight_ml.storage import DataUnavailable, DatabaseSettings, connect

WINDOW = {"location": "hai-chau", "start_date": "2023-06-01", "end_date": "2024-02-29"}


def test_empty_training_is_rejected():
    with pytest.raises(DataUnavailable):
        train_clusters([], 3)


def test_k_scan_reports_two_through_six_and_keeps_three_default():
    rows = [
        {
            "rainfall": float(i % 3),
            "intensity": float(i % 3),
            "rainy_hours": float(i % 4),
            "humidity": 60 + float(i % 5),
            "temperature": 20 + float(i % 6),
            "wind": float(i % 7),
        }
        for i in range(30)
    ]
    default_artifact, default_metrics = train_clusters(rows, 3)
    assert default_metrics["selected_clusters"] == 3
    assert default_metrics["silhouette_scores"] is None

    _, scan_metrics = train_clusters(rows, 3, scan_k=True)
    assert set(scan_metrics["silhouette_scores"]).issubset({"2", "3", "4", "5", "6"})
    assert scan_metrics["selected_clusters"] in range(2, 7)


def test_clustering_training_and_regeneration():
    if os.getenv("FLOODINSIGHT_RUN_ML_DB_TESTS") != "1":
        pytest.skip("Requires the real ERA5 sample in a disposable database")
    assert DatabaseSettings().db == "floodinsight_ml_test"
    with TestClient(app) as client:
        response = client.post("/clustering/train", json=WINDOW | {"clusters": 3})
        assert response.status_code == 200, response.text
        model = response.json()
        version = model["version"]
        metrics = client.get("/clustering/metrics", params={"version": version}).json()["metrics"]
        assert metrics["samples"] >= 200
        assert -1 <= metrics["silhouette_score"] <= 1
        assert sum(row["days"] for row in metrics["cluster_statistics"]) == metrics["samples"]
        request = WINDOW | {"version": version}
        result = client.post("/clustering/run", json=request)
        assert result.status_code == 200, result.text
        count = result.json()["stored_rows"]
        assert count == metrics["samples"]
        assert len(result.json()["option"]["series"]) == 3
        query = {"version": version, "limit": 1000}
        original = client.get("/clustering/results", params=query).json()
        assert len(original) == count
        with connect() as conn:
            conn.execute("DELETE FROM clustering_results WHERE model_version_id = %s", (model["id"],))
        assert client.get("/clustering/results", params=query).json() == []
        assert client.post("/clustering/run", json=request).status_code == 200
        assert client.get("/clustering/results", params=query).json() == original
        print("CLUSTERING_METRICS", metrics)

