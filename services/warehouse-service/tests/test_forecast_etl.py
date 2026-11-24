import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from floodinsight_warehouse.config import DatabaseSettings
from floodinsight_warehouse.repositories.forecasts import materialize_forecast_facts
from floodinsight_warehouse.repositories.models import (
    DataSource,
    DimLocation,
    FactWeatherForecastHourly,
    IngestionRun,
    RawWeatherForecast,
)
from floodinsight_warehouse.schemas.historical import ForecastETLRequest


def test_forecast_etl_request_is_limited_to_31_days():
    ForecastETLRequest(start_date="2026-11-25", end_date="2026-12-25")
    with pytest.raises(ValidationError):
        ForecastETLRequest(start_date="2026-11-26", end_date="2026-11-25")
    with pytest.raises(ValidationError):
        ForecastETLRequest(start_date="2026-11-01", end_date="2026-12-02")


def test_hourly_snapshots_materialize_idempotently_with_interval_start():
    if os.getenv("FLOODINSIGHT_RUN_WAREHOUSE_DB_TESTS") != "1":
        pytest.skip("Enable only against an isolated warehouse test database.")
    settings = DatabaseSettings()
    if settings.db != "floodinsight_warehouse_test":
        pytest.fail("The database must be named floodinsight_warehouse_test.")

    start_date = date(2026, 11, 25)
    lower = datetime(2026, 11, 24, 17, tzinfo=timezone.utc)
    received_at = lower - timedelta(hours=1)
    engine = create_engine(settings.url())
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                source_id = conn.scalar(
                    pg_insert(DataSource)
                    .values(
                        code="open-meteo-forecast-api",
                        provider="Open-Meteo",
                        dataset="Forecast API (best match)",
                    )
                    .on_conflict_do_nothing(index_elements=["code"])
                    .returning(DataSource.id)
                )
                if source_id is None:
                    source_id = conn.scalar(
                        select(DataSource.id).where(DataSource.code == "open-meteo-forecast-api")
                    )
                run_id = conn.scalar(
                    insert(IngestionRun)
                    .values(source_id=source_id, run_key=uuid4().hex)
                    .returning(IngestionRun.id)
                )
                location_code = "test-forecast-" + uuid4().hex
                location_id = conn.scalar(
                    insert(DimLocation)
                    .values(
                        code=location_code,
                        name="Test forecast point",
                        latitude=16,
                        longitude=108,
                    )
                    .returning(DimLocation.id)
                )

                first_payload = {
                    "kind": "hourly",
                    "interval_seconds": 3600,
                    "values": {
                        "rain": 1.25,
                        "temperature_2m": 25.0,
                        "relative_humidity_2m": 80.0,
                        "wind_speed_10m": 2.0,
                    },
                }
                raw_rows = [
                    {
                        "source_id": source_id,
                        "ingestion_run_id": run_id,
                        "source_location_key": location_code,
                        "valid_at": lower + timedelta(hours=index + 1),
                        "received_at": received_at,
                        "issued_at": None,
                        "snapshot_hash": f"{index:064x}",
                        "payload": first_payload,
                    }
                    for index in range(2)
                ]
                conn.execute(insert(RawWeatherForecast), raw_rows)

                first = materialize_forecast_facts(conn, start_date, start_date)
                replay = materialize_forecast_facts(conn, start_date, start_date)
                facts = conn.execute(
                    select(
                        FactWeatherForecastHourly.hour_start_utc,
                        FactWeatherForecastHourly.issued_at,
                        FactWeatherForecastHourly.snapshot_received_at,
                        FactWeatherForecastHourly.rainfall_mm,
                    )
                    .where(FactWeatherForecastHourly.location_id == location_id)
                    .order_by(FactWeatherForecastHourly.hour_start_utc)
                ).all()
                assert first["rows_upserted"] == 2
                assert replay["rows_upserted"] == 2
                assert [row.hour_start_utc for row in facts] == [lower, lower + timedelta(hours=1)]
                assert all(row.issued_at is None for row in facts)
                assert all(row.snapshot_received_at == received_at for row in facts)
                assert [float(row.rainfall_mm) for row in facts] == [1.25, 1.25]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
