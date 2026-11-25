from datetime import date, datetime, timezone
from unittest import TestCase
from unittest.mock import patch

import httpx
import numpy as np

from floodinsight_warehouse.services.flood_rasters import horn_slope

from floodinsight_warehouse.services.flood_sources import (
    POINTS, SOIL, collect, elevation_rows, fetch, hourly_rows,
)


class TestFloodSources(TestCase):
    def test_elevation_preserves_point_order_and_skips_null(self):
        rows = list(elevation_rows({"elevation": [8, None, 7, 5, 10]}))
        self.assertEqual([row["location"] for row in rows], [p.code for p in POINTS if p != POINTS[1]])
        self.assertEqual(rows[0]["unit"], "m")
        with self.assertRaises(ValueError):
            list(elevation_rows({"elevation": [8]}))

    def test_hourly_validation_preserves_zero_and_grid(self):
        payload = {
            "latitude": 16.0, "longitude": 108.25, "utc_offset_seconds": 0,
            "hourly_units": {"time": "unixtime", SOIL: "m³/m³"},
            "hourly": {"time": [1697155200, 1697158800], SOIL: [0, None]},
        }

        def parse(data):
            return list(hourly_rows(data, SOIL, "m³/m³", "hai-chau", (16.076345, 108.221783), (0, 1)))

        row, = parse(payload)
        self.assertEqual(row["value"], 0)
        self.assertEqual(row["grid_latitude"], 16.0)
        self.assertEqual(row["valid_at"], datetime(2023, 10, 13, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            parse(payload | {"hourly": {"time": [1697155200, 1697162400], SOIL: [0, None]}})
        with self.assertRaises(ValueError):
            parse(payload | {"hourly_units": {"time": "unixtime", SOIL: "mm"}})
        with self.assertRaises(ValueError):
            list(hourly_rows(payload, SOIL, "m³/m³", "hai-chau", (16, 108), (0, 1),
                             date(2023, 10, 13), date(2023, 10, 13)))

    def test_rate_limit_retries_and_invalid_request_does_not(self):
        with patch("floodinsight_warehouse.services.flood_sources.sleep") as wait:
            responses = iter([httpx.Response(429, headers={"Retry-After": "2"}),
                              httpx.Response(200, json={"elevation": [8]})])
            with httpx.Client(transport=httpx.MockTransport(lambda _: next(responses))) as client:
                _, payload = fetch(client, "https://example.test/elevation", {})
            self.assertEqual(payload, {"elevation": [8]})
            wait.assert_called_once_with(2)
            with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(400))) as client:
                with self.assertRaises(httpx.HTTPStatusError):
                    fetch(client, "https://example.test/elevation", {})
            wait.assert_called_once()

    def test_reviewed_report_does_not_create_a_label(self):
        batch, = list(collect(None, "official-events"))
        event, = batch["rows"]
        self.assertEqual(batch["kind"], "events")
        self.assertIn("October 2022", event["boundary_vintage"])
        self.assertNotIn("label", event)

    def test_horn_slope_uses_metric_spacing(self):
        values = np.array([[0, 30, 60], [0, 30, 60], [0, 30, 60]], dtype=float)
        self.assertAlmostEqual(horn_slope(values, 30, 15), 45)
        self.assertEqual(horn_slope(np.zeros((3, 3)), 30, 15), 0)
