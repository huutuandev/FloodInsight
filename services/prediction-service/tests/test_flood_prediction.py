from datetime import datetime, timedelta, timezone
import json
import os
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

import numpy as np
from sklearn.linear_model import LogisticRegression

from floodinsight_ml.flood_models import candidates, choose_threshold, development, metrics, probabilities
from floodinsight_ml.flood_training_data import FEATURES, TrainingSpec, grid_groups, input_ready, partition
from floodinsight_prediction.config import Settings
from floodinsight_prediction.flood_training import SERVABLE, train
from floodinsight_prediction.routes.flood_prediction import score


ISSUE = datetime(2025, 1, 1, tzinfo=timezone.utc)
ERA = ("open-meteo-archive-era5", 16.0, 108.25)
FC = ("open-meteo-forecast-api", 16.1, 108.2)


def fixture_row(index, value, location="fixture"):
    issue = ISSUE + timedelta(days=index)
    end = issue + timedelta(days=1)
    return {
        "location": location, "mode": "operational", "issued_at": issue, "target_end": end,
        "features": dict(zip(FEATURES, (20.0, 10.0, 3.0, 10.0, .8))),
        "weather_bins": [(ERA, issue), (FC, end)],
        "provenance": {key: {"available_at": issue} for key in FEATURES},
        "label": {"value": value, "status": "positive" if value else "negative", "confidence": "high",
                  "event_keys": [f"fixture-{index}"] if value else [],
                  "event_windows": [(issue, end)] if value else [], "available_at": end},
    }


class TestFloodPrediction(TestCase):
    def test_inventory_blocks_loading_study_or_fitting(self):
        db = MagicMock()
        with (
            patch("floodinsight_prediction.flood_training.connect") as connection,
            patch("floodinsight_prediction.flood_training.inventory",
                  return_value={"status": "insufficient_training_data"}),
            patch("floodinsight_prediction.flood_training.dataset") as dataset,
            patch("floodinsight_prediction.flood_training.development") as development,
        ):
            connection.return_value.__enter__.return_value = db
            self.assertEqual(train(None, Settings())["status"], "insufficient_training_data")
            dataset.assert_not_called()
            development.assert_not_called()

    def test_late_feature_and_retrospective_rows_are_ineligible(self):
        row = fixture_row(0, 1)
        self.assertTrue(input_ready(row))
        self.assertFalse(input_ready(row | {"mode": "retrospective"}))
        row["provenance"][FEATURES[0]]["available_at"] += timedelta(seconds=1)
        self.assertFalse(input_ready(row))

    def test_partition_rejects_shared_grids_and_purges_late_labels(self):
        roles = {"fit": ["a"], "calibration": ["b"], "selection": ["c"], "test": ["d"]}
        dates = [ISSUE + timedelta(days=i * 65) for i in range(5)]
        spec = TrainingSpec(start=dates[0], end=dates[4], as_of=dates[4], cutoffs=tuple(dates[1:4]),
                            locations=roles, surveillance_reference="unit-test only")
        row = fixture_row(64, 1, "a")
        groups = grid_groups("abcd", [{"points": ["a", "b"]}, {"points": ["c", "b"]}])
        _, report = partition([row], groups, spec)
        self.assertEqual(report["status"], "insufficient_training_data")
        self.assertTrue(any("shared weather-grid" in reason for reason in report["blockers"]))
        self.assertEqual(report["partitions"]["fit"]["purged"], 1)

    def test_metrics_and_threshold_use_row_false_alarms_and_event_misses(self):
        rows = [fixture_row(i, label) for i, label in enumerate((1, 1, 0, 0))]
        prob = np.array([.8, .2, .6, .1])
        result = metrics(rows, prob, prob >= .5)
        self.assertEqual(result["confusion"], {"tn": 1, "fp": 1, "fn": 1, "tp": 1})
        self.assertEqual(result["event_performance"]["missed_rate"], .5)
        self.assertAlmostEqual(result["brier"], .2625)
        self.assertLessEqual(choose_threshold(rows, prob), .2)

    def test_candidate_family_and_calibrated_inference(self):
        self.assertEqual(set(candidates()), {"logistic_regression", "random_forest", "hist_gradient_boosting"})
        x_train = np.arange(50, dtype=float).reshape(10, 5)
        y_train = np.array([0] * 5 + [1] * 5)
        # Small, unit-only arrays verify the two-step scoring contract. No registry writes.
        estimator = LogisticRegression().fit(x_train, y_train)
        sigmoid = LogisticRegression().fit(np.array([-3, -2, 2, 3]).reshape(-1, 1), [0, 0, 1, 1])
        row = fixture_row(0, 1)
        reference = np.asarray(list(row["features"].values()))
        artifact = {"estimator": estimator, "calibrator": sigmoid, "calibration": "sigmoid", "reference": reference}
        coverage = {"weather_grids": [ERA, FC], "feature_range": {name: (0, 100) for name in FEATURES}}
        metadata = {"validated_locations": {"fixture": coverage}, "threshold": .5}
        result, status = score(row, metadata, artifact)
        self.assertEqual(status, "predicted")
        self.assertAlmostEqual(result["flood_probability"], probabilities(artifact, reference.reshape(1, -1))[0])
        self.assertTrue(all(info["probability_change_from_median_probe"] == 0
                            for info in result["feature_contributions"].values()))
        self.assertEqual(score(row | {"location": "different"}, metadata, artifact)[1], "location_not_validated")
        weather = [(ERA, ISSUE), (("open-meteo-forecast-api", 0, 0), ISSUE)]
        self.assertEqual(score(row | {"weather_bins": weather}, metadata, artifact)[1], "weather_grid_not_validated")
        self.assertEqual(SERVABLE["release_status"], "approved")

    def test_development_runs_all_candidate_families_on_isolated_unit_fixtures(self):
        # Fixtures test the code path only. They never enter the warehouse or registry.
        parts = {}
        for offset, role in enumerate(("fit", "calibration", "selection", "test")):
            parts[role] = []
            for i in range(48):
                high = i % 4 >= 2
                label = int(high if i % 7 else not high)
                row = fixture_row(offset * 100 + i, label, role)
                row["features"][FEATURES[0]] = (85 if high else 10) + i / 20
                row["features"][FEATURES[1]] = (45 if high else 5) + i / 30
                parts[role].append(row)
        _, report = development(parts)
        self.assertEqual({item["candidate"] for item in report["candidates"]}, set(candidates()))
        self.assertTrue(all(item.get("status") == "insufficient_calibration_support"
                            for item in report["candidates"] if item["method"] == "isotonic"))


@skipUnless(os.environ.get("FLOODINSIGHT_RUN_FLOOD_MODEL_INTEGRATION") == "1", "Requires the isolated Phase 1 stack")
class TestFloodPredictionIntegration(TestCase):
    def call(self, path, payload=None):
        request = Request("http://api-service:8000/api/v1" + path,
                          data=json.dumps(payload).encode() if payload else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            return json.load(response)["data"]

    def test_unready_prediction_does_not_use_rainfall_models_or_write_probability(self):
        report = self.call("/flood-prediction/readiness")
        self.assertEqual(report["status"], "insufficient_training_data")
        self.assertEqual(report["inventory"]["flood_registry_rows"], 0)
        result = self.call("/flood-prediction/predict",
                           {"location": "hai-chau", "issued_at": "2026-11-25T14:00:00Z",
                            "version": "b9acec0f9d9a45c4a2d5be1fbfc2a2cc"})
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertIsNone(result["flood_probability"])
        self.assertIsNone(result["model_version"])
        self.assertEqual(self.call("/flood-prediction/readiness")["inventory"]["flood_probability_rows"], 0)
        stored = self.call("/flood-risk/assessments?location=hai-chau")
        self.assertTrue(stored)
        self.assertEqual(stored[0]["risk_category"], "Insufficient Data")
