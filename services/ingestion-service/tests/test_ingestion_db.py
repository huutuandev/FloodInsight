import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from floodinsight_ingestion.config import DatabaseSettings, Settings
from floodinsight_ingestion.main import create_app
from floodinsight_ingestion.repositories import ingestion as repository
from floodinsight_ingestion.schemas.open_meteo import ForecastResponse
from floodinsight_ingestion.services.open_meteo import (
    DANANG_POINTS,
    OpenMeteoClient,
    ProviderError,
    to_snapshots,
)


@pytest.fixture
def isolated_source(monkeypatch):
    if os.getenv("FLOODINSIGHT_RUN_INGESTION_DB_TESTS") != "1":
        pytest.skip("Enable only with a disposable migrated PostgreSQL database.")
    db = DatabaseSettings()
    if db.db != "floodinsight_ingestion_test":
        pytest.fail("Use the dedicated floodinsight_ingestion_test database.")
    monkeypatch.setattr(repository, "SOURCE_CODE", "test-" + uuid4().hex)
    return db


@pytest.fixture
def recorded_snapshots():
    path = Path(__file__).parent / "fixtures" / "open_meteo_hai_chau.json"
    recorded = ForecastResponse.model_validate_json(path.read_bytes())
    return to_snapshots(DANANG_POINTS[0], recorded, datetime.now(timezone.utc))


def test_routes_persist_deduplicate_and_recover(isolated_source, recorded_snapshots, monkeypatch):
    outcomes = iter([ProviderError("test outage"), recorded_snapshots, recorded_snapshots])

    async def fetch(provider):
        outcome = next(outcomes)
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome

    monkeypatch.setattr(OpenMeteoClient, "fetch", fetch)
    with TestClient(create_app(Settings(scheduler_enabled=False))) as client:
        assert client.post("/ingestion/run").status_code == 502
        assert client.get("/ingestion/latest").json() == []
        first = client.post("/ingestion/run")
        assert first.status_code == 200
        assert first.json()["records_inserted"] == 3
        replay = client.post("/ingestion/run").json()
        assert replay["records_inserted"] == 0
        with psycopg.connect(
            host=isolated_source.host, port=isolated_source.port, dbname=isolated_source.db,
            user=isolated_source.user, password=isolated_source.password.get_secret_value(),
        ) as conn:
            receipts = conn.execute("""
                SELECT run_id, count(*) FROM forecast_snapshot_receipts
                WHERE run_id IN (%s, %s) GROUP BY run_id ORDER BY run_id
            """, (first.json()["id"], replay["id"])).fetchall()
        assert receipts == [(first.json()["id"], 2), (replay["id"], 2)]
        history = client.get("/ingestion/history", params={"limit": 2, "offset": 1}).json()
        assert [row["status"] for row in history] == ["succeeded", "failed"]
        assert history[-1]["error_message"] == "test outage"
        assert client.get("/ingestion/status").json()["latest_run"]["id"] == replay["id"]
        latest = client.get("/ingestion/latest").json()
        assert len(latest) == 1
        assert latest[0]["issued_at"] is None
        assert latest[0]["received_at"] != latest[0]["valid_at"]


def test_scheduler_and_manual_execution_share_lock(
    isolated_source, recorded_snapshots, monkeypatch
):
    async def fetch(provider):
        return recorded_snapshots

    monkeypatch.setattr(OpenMeteoClient, "fetch", fetch)
    settings = Settings(scheduler_enabled=True, interval_seconds=1)
    db = isolated_source
    with TestClient(create_app(settings)) as client:
        with psycopg.connect(
            host=db.host, port=db.port, dbname=db.db, user=db.user,
            password=db.password.get_secret_value(), autocommit=True,
        ) as locked:
            locked.execute("SELECT pg_advisory_lock(%s)", (repository.LOCK_KEY,))
            assert client.post("/ingestion/run").status_code == 409
            time.sleep(1.2)
            assert client.get("/ingestion/history").json() == []
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            status = client.get("/ingestion/status").json()
            run = status["latest_run"]
            if run is not None and run["status"] == "succeeded":
                assert run["trigger"] == "scheduled"
                assert status["next_run_at"] is not None
                break
            time.sleep(0.1)
        else:
            pytest.fail("APScheduler did not complete a run")


def test_reclaims_interrupted_run(isolated_source, recorded_snapshots, monkeypatch):
    async def interrupt():
        repo = repository.IngestionRepository()
        async with repo.exclusive_run() as conn:
            _, stale_run = await repo.start(conn, "scheduled")
            return stale_run

    async def fetch(provider):
        return recorded_snapshots

    stale_run = asyncio.run(interrupt())
    monkeypatch.setattr(OpenMeteoClient, "fetch", fetch)
    with TestClient(create_app(Settings(scheduler_enabled=False))) as client:
        assert client.post("/ingestion/run").status_code == 200
        stale = client.get("/ingestion/history").json()[1]
        assert stale["id"] == stale_run
        assert stale["status"] == "failed"
        assert stale["finished_at"] is not None
