import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from floodinsight_warehouse.config import DatabaseSettings
from floodinsight_warehouse.main import app
from floodinsight_warehouse.repositories import historical as repository
from floodinsight_warehouse.schemas.historical import ArchiveResponse
from floodinsight_warehouse.services import historical, pipeline
from floodinsight_warehouse.services.historical import ArchiveClient, ArchiveError, POINTS
from floodinsight_warehouse.services.ml_dataset import chronological_rainfall_splits
from floodinsight_warehouse.services.transform import transform_hours

DAY = date(2023, 10, 13)
HOUR = timedelta(hours=1)
POINT = POINTS[0]
ARCHIVE = Path(__file__).parent / "fixtures" / "open_meteo_era5_hai_chau_2023-10-13.json"


def test_historical_points_match_the_live_ingestion_network():
    assert [point.code for point in POINTS] == [
        "hai-chau", "thanh-khe", "lien-chieu", "cam-le", "ngu-hanh-son",
        "son-tra", "hoa-vang", "hoa-bac", "hoa-khuong",
    ]


def sample_records():
    return historical.archive_records(
        ArchiveResponse.model_validate_json(ARCHIVE.read_bytes()), POINT,
        *historical.utc_bounds(DAY, DAY), datetime.now(timezone.utc)
    )


def test_retry_and_provider_time_axis(monkeypatch):
    monkeypatch.setattr(historical, "sleep", lambda delay: None)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=ARCHIVE.read_bytes())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        rows = ArchiveClient(http, "https://archive-api.open-meteo.com/v1/archive", 2).fetch(
            POINT, DAY, DAY
        )
    assert len(requests) == 2
    assert requests[-1].url.params["models"] == "era5"
    assert requests[-1].url.params["start_date"] == "2023-10-12"
    assert len(rows) == 25
    assert rows[0].valid_at == datetime(2023, 10, 12, 17, tzinfo=timezone.utc)
    assert rows[-1].valid_at - rows[0].valid_at == timedelta(days=1)


def test_interval_alignment_and_missing_rain():
    lower, upper = historical.utc_bounds(DAY, DAY)
    raw = {row.valid_at: row.payload["values"] for row in sample_records()}
    hours, report = transform_hours(raw, lower, upper)
    assert hours[0]["rainfall_mm"] == Decimal("2.000")
    assert hours[0]["air_temperature_c"] == Decimal("25.60")
    assert sum(row["rainfall_mm"] for row in hours) == Decimal("73.600")
    assert report["rainfall_coverage_hours"] == 24

    del raw[upper]
    hours, report = transform_hours(raw, lower, upper)
    assert hours[-1]["rainfall_mm"] is None
    assert hours[-1]["air_temperature_c"] is not None
    assert report["missing_values"]["rainfall_mm"] == 1
    assert report["missing_raw_timestamps"] == 1
    assert report["rainfall_coverage_hours"] == 23


def test_monthly_chunks_cover_multiyear_range():
    start, end = date(2022, 1, 1), date(2024, 12, 31)
    batches = list(historical.month_batches(start, end))
    assert len(batches) == 36
    assert batches[0][0] == start
    assert batches[-1][1] == end
    assert sum((last - first).days + 1 for first, last in batches) == 1096


def test_ml_split_filters_availability_and_embargoes_crossing_targets():
    lower, upper = historical.utc_bounds(DAY, DAY)
    records = sample_records()
    hours, _ = transform_hours(
        {row.valid_at: row.payload["values"] for row in records}, lower, upper
    )
    rows = pd.DataFrame([
        row | {"location_id": 1, "weather_source_id": 1, "received_at": records[0].received_at}
        for row in hours
    ])
    cutoff = lower + 12 * HOUR
    train, test = chronological_rainfall_splits(rows, cutoff)
    assert train.empty and test.empty

    # Exercise the split with simulated availability and the same real measurements.
    rows["received_at"] = rows["hour_start_utc"] + HOUR
    train, test = chronological_rainfall_splits(rows, cutoff, lookback_hours=1)
    assert not train.empty and not test.empty
    assert (train["target_hour_utc"] + HOUR <= cutoff).all()
    assert (test["issue_at"] >= cutoff).all()
    assert (train["target_hour_utc"] - train["issue_at"] == HOUR).all()
    assert not train["issue_at"].isin([cutoff - HOUR]).any()


def test_checkpoint_etl_replay_and_sql_aggregates(monkeypatch):
    if os.getenv("FLOODINSIGHT_RUN_WAREHOUSE_DB_TESTS") != "1":
        pytest.skip("Requires an isolated, migrated PostgreSQL database.")
    db = DatabaseSettings()
    if db.db != "floodinsight_warehouse_test":
        pytest.fail("Use the dedicated floodinsight_warehouse_test database.")
    code = "test-" + uuid4().hex
    monkeypatch.setattr(repository, "SOURCE_CODE", code)
    monkeypatch.setattr(pipeline, "POINTS", (POINT,))
    responses = iter([ArchiveError("test outage"), sample_records()])

    def fetch(self, point, start, end):
        result = next(responses)
        if isinstance(result, ArchiveError):
            raise result
        return result

    monkeypatch.setattr(ArchiveClient, "fetch", fetch)
    payload = {"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}
    with TestClient(app) as client:
        assert client.post("/warehouse/backfill", json=payload).json()["status"] == "failed"
        collected = client.post("/warehouse/backfill", json=payload).json()
        assert collected["progress"]["raw_rows_inserted"] == 25
        assert client.post("/warehouse/backfill", json=payload).json()["progress"]["batches_processed"] == 0
        loaded = client.post("/warehouse/etl/run", json=payload).json()
        assert loaded["status"] == "succeeded"
        assert loaded["progress"]["hourly_rows_loaded"] == 24
        assert client.post("/warehouse/etl/run", json=payload).json()["progress"]["batches_processed"] == 0
        rerun = client.post("/warehouse/etl/run", json=payload | {"reprocess": True}).json()
        assert rerun["progress"]["hourly_rows_loaded"] == 24
        assert client.get("/warehouse/quality").json()[0]["quality"]["rainfall_coverage_hours"] == 24
        assert client.get("/warehouse/status").json()["runs"][0]["id"] == rerun["id"]

    engine = create_engine(db.url())
    try:
        with engine.connect() as conn:
            # PostgreSQL's plain AT TIME ZONE conversion chooses the later
            # midnight during this historical offset change.
            repeated_day = date(1955, 7, 1)
            upper_day = repeated_day + timedelta(days=1)
            assert conn.execute(text("""
                SELECT warehouse_local_day_start(:start), warehouse_local_day_start(:end)
            """), {"start": repeated_day, "end": upper_day}).one() == historical.utc_bounds(
                repeated_day, repeated_day
            )
            assert historical.utc_bounds(repeated_day, repeated_day)[1] - historical.utc_bounds(
                repeated_day, repeated_day
            )[0] == 25 * HOUR

            raw_count = conn.scalar(text("""
                SELECT count(*) FROM raw_weather_observations r
                JOIN data_sources d ON r.source_id = d.id WHERE d.code = :code
            """), {"code": code})
            assert raw_count == 25
            periods = [
                ("vw_weather_daily", DAY, 24),
                ("vw_weather_weekly", date(2023, 10, 9), 168),
                ("vw_weather_monthly", date(2023, 10, 1), 744),
            ]
            for view, start, expected in periods:
                assert conn.execute(text(f"""
                    SELECT period_start, rainfall_total_mm, rainfall_hours, expected_hours
                    FROM {view} v JOIN dim_weather_source w ON w.id = v.weather_source_id
                    JOIN data_sources d ON d.id = w.data_source_id WHERE d.code = :code
                """), {"code": code}).one() == (start, Decimal("73.600"), 24, expected)
            assert conn.execute(text("""
                SELECT local_date, rainfall_total_mm, hours_with_rainfall
                FROM fact_rainfall_daily f JOIN dim_weather_source w ON w.id = f.weather_source_id
                JOIN data_sources d ON d.id = w.data_source_id WHERE d.code = :code
            """), {"code": code}).one() == (DAY, Decimal("73.600"), 24)
    finally:
        engine.dispose()

