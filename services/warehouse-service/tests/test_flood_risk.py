from datetime import datetime, timedelta, timezone
import json
import os
from unittest import TestCase, skipUnless
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from floodinsight_ml.flood_risk import FACTORS, RiskConfig, assess, category, sensitivity
from floodinsight_ml.flood_risk_validation import evaluate


ISSUE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def feature_row(**updates):
    data = dict(zip((key for group in FACTORS.values() for key in group), (50, 50, 25, 10, .5, .35)))
    data.update(updates)
    return {
        "issued_at": ISSUE, "mode": "operational", "location": "unit-test",
        "latitude": 16.0, "longitude": 108.0, "weather_bins": [], "features": data,
        "provenance": {key: {"available_at": ISSUE, "source_ids": []} for key in data},
    }


class TestFloodRisk(TestCase):
    def setUp(self):
        self.config = RiskConfig()

    def test_contributions_sum_to_index_and_probability_is_always_null(self):
        result = assess(feature_row(), self.config)
        self.assertEqual(result["risk_index"], 50)
        self.assertEqual(result["risk_category"], "High")
        self.assertAlmostEqual(sum(factor["contribution_points"] for factor in result["factors"].values()), 50)
        self.assertIsNone(result["flood_probability"])
        self.assertEqual(result["forecast_horizon_hours"], 24)

    def test_critical_missing_and_late_provenance_abstain(self):
        row = feature_row(forecast_rain_next_24h_mm=None)
        row["provenance"]["rain_prev_24h_mm"]["available_at"] = ISSUE + timedelta(hours=1)
        result = assess(row, self.config)
        self.assertIsNone(result["risk_index"])
        self.assertEqual(result["risk_category"], "Insufficient Data")
        self.assertEqual(result["missing_critical_factors"], ["forecast_rainfall", "recent_rainfall"])
        self.assertIsNone(sensitivity(row, self.config))

    def test_only_noncritical_missing_can_produce_a_limited_index(self):
        result = assess(feature_row(soil_moisture_delayed=None), self.config)
        self.assertEqual(result["assessment_status"], "limited")
        self.assertEqual(result["risk_index"], 50)
        self.assertIsNone(result["factors"]["soil_wetness"]["contribution_points"])
        self.assertEqual(result["missing_features"], ["soil_moisture_delayed"])

    def test_clipping_and_boundary_inclusivity(self):
        self.assertEqual([category(x, self.config) for x in (0, 25, 50, 75, 100)],
                         ["Low", "Moderate", "High", "Very High", "Very High"])
        dry = feature_row(forecast_rain_next_24h_mm=0, rain_prev_24h_mm=0, rain_max_hour_prev_24h_mm=0,
                          elevation_m=100, built_up_fraction=0, soil_moisture_delayed=.1)
        self.assertEqual(assess(dry, self.config)["risk_index"], 0)
        self.assertEqual(assess(feature_row(forecast_rain_next_24h_mm=400, rain_prev_24h_mm=120,
                                            rain_max_hour_prev_24h_mm=100, elevation_m=0,
                                            built_up_fraction=1, soil_moisture_delayed=.6),
                                self.config)["risk_index"], 100)

    def test_invalid_configuration_and_disallowed_reanalysis(self):
        with self.assertRaises(ValidationError):
            RiskConfig(weights={"forecast_rainfall": 1})
        with self.assertRaises(ValidationError):
            RiskConfig(category_starts=(30, 30, 50))
        with self.assertRaises(ValueError):
            assess(feature_row() | {"mode": "retrospective"}, self.config)

    def test_sensitivity_discloses_boundary_crossings(self):
        result = sensitivity(feature_row(), self.config)
        self.assertEqual(result["trials"], 22)
        self.assertLess(result["min"], 50)
        self.assertGreater(result["max"], 50)
        self.assertEqual(result["categories"], ["Moderate", "High"])

    def test_backtest_excludes_unknown_and_reports_undefined_metrics(self):
        row = feature_row()
        row["issued_at"] = ISSUE.isoformat()
        for item in row["provenance"].values():
            item["available_at"] = ISSUE.isoformat()
        result = evaluate({"schema": "flood-point-v1", "mode": "operational",
                           "rows": [row | {"label": {"status": "unknown"}}]}, self.config)
        self.assertEqual(result["validation_status"], "not_evaluable")
        self.assertIsNone(result["confusion_scored_only"])
        self.assertIsNone(result["sensitivity_scored_only"])


@skipUnless(os.environ.get("FLOODINSIGHT_RUN_RISK_DB_TESTS") == "1", "Requires the isolated Phase 1 stack")
class TestFloodRiskIntegration(TestCase):
    def call(self, path, payload=None):
        url = os.environ.get("FLOODINSIGHT_TEST_GATEWAY_URL", "http://api-service:8000/api/v1") + path
        request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            return json.load(response)["data"]

    def test_persist_read_and_replay_abstention(self):
        path = "/flood-risk/assessments"
        payload = {"location": "hai-chau", "issued_at": "2026-11-25T14:00:00Z"}
        saved = self.call(path, payload)
        self.assertIsNone(saved["flood_probability"])
        self.assertIsNone(saved["risk_index"])
        self.assertEqual(saved["risk_category"], "Insufficient Data")
        self.assertIn("terrain", saved["factors"])
        self.assertEqual(self.call(path, payload)["id"], saved["id"])
        stored = self.call(path + "?location=hai-chau")
        self.assertIn(saved["id"], [row["id"] for row in stored])
        with self.assertRaises(HTTPError) as error:
            self.call(path, payload | {"issued_at": "2026-11-25T14:01:00Z"})
        self.assertEqual(error.exception.code, 422)

    def test_terrain_profiles_are_exploratory(self):
        response = self.call("/clustering/flood-profiles?issued_at=2026-11-25T14%3A00%3A00Z&clusters=2")
        self.assertEqual(response["complete_points"], 5)
        self.assertEqual(len(response["cluster_sizes"]), 2)
        self.assertIn("without flood labels", response["interpretation"])
