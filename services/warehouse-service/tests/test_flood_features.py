from datetime import datetime, timedelta, timezone
from unittest import TestCase

from floodinsight_ml.availability import ERA5_DELAY
from floodinsight_ml.flood_features import HOUR, TARGET, make_row, target, validate_holdout
from floodinsight_warehouse.flood_dataset import episode_count, quality, spatial_groups


ISSUE = datetime(2026, 1, 20, tzinfo=timezone.utc)
POINT = {"id": 1, "code": "point", "latitude": 16.0, "longitude": 108.0}
EMPTY = {name: [] for name in ("rain", "forecast", "terrain", "hydrology", "observations")}
GRID = ("test", 16.0, 108.0)


def observation(**changes):
    return dict(id=1, location_id=1, latitude=16.0, longitude=108.0, quality="high",
                spatial_uncertainty_m=10, source="test", event_key="test-event",
                label="flood_confirmed", observed_at=ISSUE + HOUR, available_at=ISSUE + 2 * HOUR,
                event_start=ISSUE, event_end=ISSUE + TARGET, coverage_evidence=None,
                coverage_start=None, coverage_end=None, coverage_radius_m=None) | changes


def rain_rows(start, values, receipt):
    return [dict(hour=start + i * HOUR, rain=value, received_at=receipt, id=i, source="test",
                 weather_bin=(GRID, start + (i + 1) * HOUR)) for i, value in enumerate(values)]


class TestFloodFeatures(TestCase):
    def test_late_weather_receipt_is_excluded_and_no_missing_to_zero(self):
        rain = rain_rows(ISSUE - TARGET, [0] * 24, ISSUE + HOUR)
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "operational", EMPTY | {"rain": rain})
        self.assertIsNone(row["features"]["rain_prev_24h_mm"])
        rain = rain_rows(ISSUE - TARGET, [0] * 24, ISSUE)
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "operational", EMPTY | {"rain": rain})
        self.assertEqual(row["features"]["rain_prev_24h_mm"], 0)
        self.assertIsNone(row["features"]["rain_prev_48h_mm"])
        self.assertIsNone(row["features"]["wet_hour_intensity_prev_24h_mm_per_h"])
        self.assertEqual(row["features"]["longest_wet_spell_prev_24h"], 0)

    def test_rolling_rain_statistics_and_gaps(self):
        values = [0] * 20 + [1, 2, 3, 0]
        rain = rain_rows(ISSUE - TARGET, values, ISSUE)
        features = make_row(POINT, ISSUE, ISSUE + TARGET, "operational", EMPTY | {"rain": rain})["features"]
        self.assertEqual(features["rain_max_3h_prev_24h_mm"], 6)
        self.assertEqual(features["rain_max_hour_prev_24h_mm"], 3)
        self.assertEqual(features["wet_hour_intensity_prev_24h_mm_per_h"], 2)
        self.assertEqual(features["longest_wet_spell_prev_24h"], 3)
        self.assertEqual(features["wet_hours_prev_24h"], 3)
        missing = make_row(POINT, ISSUE, ISSUE + TARGET, "operational",
                           EMPTY | {"rain": rain[:-2] + rain[-1:]})["features"]
        self.assertIsNone(missing["rain_max_3h_prev_24h_mm"])
        self.assertEqual(missing["rain_prev_1h_mm"], 0)

    def test_retrospective_uses_delay_and_excludes_real_forecasts(self):
        cutoff = ISSUE - ERA5_DELAY
        rain = rain_rows(cutoff - TARGET, [1] * 24, ISSUE + HOUR)
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "retrospective", EMPTY | {"rain": rain})
        self.assertEqual(row["features"]["antecedent_rain_delayed_24h_mm"], 24)
        self.assertIsNone(row["features"]["rain_prev_24h_mm"])
        self.assertIsNone(row["features"]["forecast_rain_next_6h_mm"])
        self.assertEqual(row["provenance"]["antecedent_rain_delayed_24h_mm"]["available_at"], ISSUE)

    def test_forecast_respects_receipt_and_never_stitches_runs(self):
        early = [dict(id=i, run_id=1, received_at=ISSUE - HOUR, issued_at=None, source="test", rain=1,
                      valid_at=ISSUE + i * HOUR, weather_bin=(GRID, ISSUE + i * HOUR)) for i in range(1, 25)]
        late = [row | {"id": row["id"] + 24, "run_id": 2, "received_at": ISSUE + HOUR, "rain": 9}
                for row in early]
        inputs = EMPTY | {"forecast": early + late}
        self.assertEqual(make_row(POINT, ISSUE, ISSUE + TARGET, "operational",
                                  inputs)["features"]["forecast_rain_next_24h_mm"], 24)
        partial = late[0] | {"received_at": ISSUE}
        self.assertIsNone(make_row(POINT, ISSUE, ISSUE + TARGET, "operational",
                                  EMPTY | {"forecast": early + [partial]})["features"]["forecast_rain_next_6h_mm"])

    def test_positive_requires_closed_horizon_link_matching_space_and_time(self):
        self.assertEqual(target(POINT, [observation()], ISSUE, ISSUE + TARGET)["value"], 1)
        self.assertIsNone(target(POINT, [observation()], ISSUE, ISSUE + HOUR)["value"])
        self.assertIsNone(target(POINT, [observation(location_id=2)], ISSUE, ISSUE + TARGET)["value"])
        self.assertIsNone(target(POINT, [observation(longitude=108.01)], ISSUE, ISSUE + TARGET)["value"])
        self.assertIsNone(target(POINT, [observation(observed_at=ISSUE)], ISSUE, ISSUE + TARGET)["value"])
        self.assertIsNone(target(POINT, [observation(available_at=ISSUE + 2 * TARGET)], ISSUE,
                                 ISSUE + TARGET)["value"])

    def test_dry_point_requires_full_interval_and_area_and_conflicts_stay_unknown(self):
        dry = observation(label="non_flood_confirmed", observed_at=ISSUE + TARGET,
                          available_at=ISSUE + TARGET, coverage_evidence="test", coverage_radius_m=60,
                          coverage_start=ISSUE, coverage_end=ISSUE + TARGET)
        self.assertEqual(target(POINT, [dry], ISSUE, ISSUE + TARGET)["value"], 0)
        self.assertIsNone(target(POINT, [dry | {"coverage_radius_m": 40}], ISSUE, ISSUE + TARGET)["value"])
        self.assertIsNone(target(POINT, [dry | {"coverage_start": ISSUE + HOUR}], ISSUE,
                                 ISSUE + TARGET)["value"])
        self.assertEqual(target(POINT, [dry, observation()], ISSUE, ISSUE + TARGET)["reason"],
                         "conflicting_evidence")

    def test_flood_history_requires_prior_evidence_and_deduplicates_event(self):
        old = observation(observed_at=ISSUE - HOUR, available_at=ISSUE - HOUR,
                          event_start=ISSUE - TARGET, event_end=ISSUE)
        late = old | {"available_at": ISSUE + HOUR, "event_key": "late"}
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "operational",
                       EMPTY | {"observations": [old, old | {"id": 2}, late, observation()]})
        self.assertEqual(row["features"]["reported_flood_events_prev_365d"], 1)
        self.assertEqual(row["label"]["value"], 1)

    def test_late_terrain_and_marine_receipts_are_excluded(self):
        dem = dict(id=1, source="dem", feature="elevation", unit="m", value=9, available_at=ISSUE + HOUR)
        tide = dict(id=2, source="marine", variable="sea_level_height_msl", value=-0.5,
                    valid_at=ISSUE, available_at=ISSUE + HOUR)
        inputs = EMPTY | {"terrain": [dem], "hydrology": [tide]}
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "operational", inputs)
        self.assertIsNone(row["features"]["elevation_m"])
        self.assertIsNone(row["features"]["offshore_sea_level_msl_m"])
        row = make_row(POINT, ISSUE + HOUR, ISSUE + TARGET, "operational", inputs)
        self.assertEqual(row["features"]["elevation_m"], 9)
        self.assertEqual(row["features"]["offshore_sea_level_msl_m"], -0.5)

    def test_holdout_and_quality_group_shared_grids_and_overlapping_events(self):
        groups = spatial_groups(["a", "b", "c"], [{"points": ["a", "b"]}, {"points": ["c", "b"]}])
        self.assertEqual(groups, [("a", "b", "c")])
        row = make_row(POINT, ISSUE, ISSUE + TARGET, "operational", EMPTY)
        self.assertEqual(quality([row], [], [])["labels"], {"positive": 0, "negative": 0, "unknown": 1})
        self.assertEqual(episode_count([observation(), observation(event_key="other")],
                                       {"test-event", "other"}), 1)
        label = {"status": "negative", "available_at": ISSUE + TARGET, "event_keys": []}
        train = row | {"location": "a", "label": label}
        test = row | {"location": "b", "label": label, "issued_at": ISSUE + 2 * TARGET}
        with self.assertRaisesRegex(ValueError, "grid"):
            validate_holdout([train], [test], groups)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_holdout([train], [test | {"issued_at": ISSUE + TARGET}], [])
        with self.assertRaisesRegex(ValueError, "recorded"):
            validate_holdout([train], [test | {"mode": "retrospective"}], [])
        validate_holdout([train], [test], [])
