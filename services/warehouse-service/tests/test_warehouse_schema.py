"""Constraint checks against a disposable, migrated PostgreSQL database."""

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from floodinsight_warehouse.config import DatabaseSettings
from floodinsight_warehouse.repositories.models import (
    ClassificationResult,
    DataSource,
    DimDate,
    DimLocation,
    DimTime,
    DimWeatherSource,
    FactRainfallDaily,
    FactWeatherForecastHourly,
    FactWeatherHourly,
    IngestionRun,
    ModelVersion,
    PredictionResult,
    RawWeatherForecast,
    RawWeatherObservation,
)

LOCAL_DATE = date(2025, 1, 2)
MIDNIGHT_UTC = datetime(2025, 1, 1, 17, tzinfo=timezone.utc)
ONE_HOUR = timedelta(hours=1)


@pytest.fixture
def db():
    if os.getenv("FLOODINSIGHT_RUN_WAREHOUSE_DB_TESTS") != "1":
        pytest.skip("Enable only against an isolated warehouse test database.")
    settings = DatabaseSettings()
    if settings.db != "floodinsight_warehouse_test":
        pytest.fail("The database must be named floodinsight_warehouse_test.")

    engine = create_engine(settings.url())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def add_source(db):
    source_id = db.scalar(
        insert(DataSource)
        .values(code=uuid4().hex, provider="test-only", dataset="schema verification")
        .returning(DataSource.id)
    )
    run_id = db.scalar(
        insert(IngestionRun)
        .values(source_id=source_id, run_key="schema-verification")
        .returning(IngestionRun.id)
    )
    return source_id, run_id


@pytest.fixture
def fact_keys(db):
    source_id, _ = add_source(db)
    weather_source_id = db.scalar(
        insert(DimWeatherSource)
        .values(data_source_id=source_id, name="test-only source")
        .returning(DimWeatherSource.id)
    )
    location_id = db.scalar(
        insert(DimLocation)
        .values(code=uuid4().hex, name="test-only location", latitude=16, longitude=108)
        .returning(DimLocation.id)
    )
    db.execute(insert(DimDate).values(local_date=LOCAL_DATE))
    db.execute(insert(DimTime).values(hour_start_utc=MIDNIGHT_UTC))
    return {"location_id": location_id, "weather_source_id": weather_source_id}


def assert_rejected(db, statement, sqlstate):
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            db.execute(statement)
    assert error.value.orig.sqlstate == sqlstate


def test_raw_observation_retry_and_source_provenance(db):
    source_id, run_id = add_source(db)
    _, unrelated_run = add_source(db)
    record = dict(
        source_id=source_id,
        ingestion_run_id=run_id,
        source_location_key="test-only",
        valid_at=MIDNIGHT_UTC,
        payload={},
    )
    db.execute(insert(RawWeatherObservation).values(**record))

    retry_run = db.scalar(
        insert(IngestionRun)
        .values(source_id=source_id, run_key="another-run")
        .returning(IngestionRun.id)
    )
    same_instant = MIDNIGHT_UTC.astimezone(timezone(timedelta(hours=7)))
    retry = insert(RawWeatherObservation).values(
        record | {"valid_at": same_instant, "ingestion_run_id": retry_run}
    )
    assert_rejected(db, retry, "23505")

    replay = pg_insert(RawWeatherObservation).values(record).on_conflict_do_nothing(
        index_elements=["source_id", "source_location_key", "valid_at"]
    )
    assert db.execute(replay.returning(RawWeatherObservation.id)).scalar_one_or_none() is None
    assert_rejected(
        db,
        insert(RawWeatherObservation).values(
            record | {"ingestion_run_id": unrelated_run, "valid_at": MIDNIGHT_UTC + ONE_HOUR}
        ),
        "23503",
    )
    assert_rejected(
        db,
        insert(IngestionRun).values(source_id=source_id, run_key="schema-verification"),
        "23505",
    )
    assert_rejected(
        db,
        insert(IngestionRun).values(source_id=source_id, run_key="invalid", status="succeeded"),
        "23514",
    )

    forecast = record | {"issued_at": MIDNIGHT_UTC - ONE_HOUR}
    db.execute(insert(RawWeatherForecast).values(forecast))
    db.execute(insert(RawWeatherForecast).values(forecast | {"issued_at": MIDNIGHT_UTC}))
    assert_rejected(db, insert(RawWeatherForecast).values(forecast), "23505")
    assert_rejected(
        db,
        insert(RawWeatherForecast).values(forecast | {"issued_at": MIDNIGHT_UTC + ONE_HOUR}),
        "23514",
    )


def test_utc_and_vietnam_calendar_boundary(db):
    assert db.scalar(text("SHOW TIME ZONE")) == "UTC"
    previous_date = LOCAL_DATE - timedelta(days=1)
    db.execute(insert(DimDate), [{"local_date": previous_date}, {"local_date": LOCAL_DATE}])
    db.execute(
        insert(DimTime),
        [
            {"hour_start_utc": MIDNIGHT_UTC - ONE_HOUR},
            {"hour_start_utc": MIDNIGHT_UTC.astimezone(timezone(timedelta(hours=7)))},
        ],
    )
    rows = db.execute(
        select(DimTime.hour_start_utc, DimTime.local_date, DimTime.local_hour)
        .where(DimTime.hour_start_utc.between(MIDNIGHT_UTC - ONE_HOUR, MIDNIGHT_UTC))
        .order_by(DimTime.hour_start_utc)
    ).all()
    assert rows == [
        (MIDNIGHT_UTC - ONE_HOUR, previous_date, 23),
        (MIDNIGHT_UTC, LOCAL_DATE, 0),
    ]
    assert rows[-1].hour_start_utc.utcoffset() == timedelta(0)
    assert_rejected(
        db,
        insert(DimTime).values(hour_start_utc=MIDNIGHT_UTC + timedelta(minutes=1)),
        "23514",
    )


def test_fact_grains_and_measure_checks(db, fact_keys):
    hourly = fact_keys | {"hour_start_utc": MIDNIGHT_UTC, "rainfall_mm": Decimal("1.250")}
    db.execute(insert(FactWeatherHourly).values(hourly))
    assert_rejected(db, insert(FactWeatherHourly).values(hourly), "23505")
    assert_rejected(
        db,
        insert(FactWeatherHourly).values(hourly | {"hour_start_utc": MIDNIGHT_UTC + ONE_HOUR}),
        "23503",
    )

    forecast = hourly | {"issued_at": MIDNIGHT_UTC - ONE_HOUR}
    db.execute(insert(FactWeatherForecastHourly).values(forecast))
    db.execute(insert(FactWeatherForecastHourly).values(forecast | {"issued_at": MIDNIGHT_UTC}))
    assert_rejected(db, insert(FactWeatherForecastHourly).values(forecast), "23505")
    assert_rejected(
        db,
        insert(FactWeatherForecastHourly).values(forecast | {"issued_at": MIDNIGHT_UTC + ONE_HOUR}),
        "23514",
    )
    assert_rejected(
        db,
        insert(FactWeatherForecastHourly).values(
            forecast | {"issued_at": MIDNIGHT_UTC - 2 * ONE_HOUR, "rainfall_mm": Decimal("NaN")}
        ),
        "23514",
    )

    daily = fact_keys | {
        "local_date": LOCAL_DATE,
        "rainfall_total_mm": Decimal("1.250"),
        "hours_with_rainfall": 1,
    }
    assert_rejected(db, insert(FactRainfallDaily).values(daily | {"hours_with_rainfall": 27}), "23514")
    db.execute(insert(FactRainfallDaily).values(daily))
    assert_rejected(db, insert(FactRainfallDaily).values(daily), "23505")


def test_daily_aggregation_uses_local_date_and_measured_coverage(db, fact_keys):
    prior_date = LOCAL_DATE - timedelta(days=1)
    db.execute(insert(DimDate).values(local_date=prior_date))
    db.execute(
        insert(DimTime),
        [
            {"hour_start_utc": MIDNIGHT_UTC - ONE_HOUR},
            {"hour_start_utc": MIDNIGHT_UTC + ONE_HOUR},
        ],
    )
    db.execute(
        insert(FactWeatherHourly),
        [
            fact_keys | {
                "hour_start_utc": MIDNIGHT_UTC - ONE_HOUR,
                "rainfall_mm": Decimal("2.500"),
                "relative_humidity_pct": None,
            },
            fact_keys | {
                "hour_start_utc": MIDNIGHT_UTC,
                "rainfall_mm": Decimal("0.000"),
                "relative_humidity_pct": None,
            },
            fact_keys | {
                "hour_start_utc": MIDNIGHT_UTC + ONE_HOUR,
                "rainfall_mm": None,
                "relative_humidity_pct": Decimal("75.00"),
            },
        ],
    )
    rows = db.execute(
        text(
            """
            SELECT t.local_date, SUM(w.rainfall_mm), COUNT(w.rainfall_mm)
            FROM fact_weather_hourly AS w
            JOIN dim_time AS t USING (hour_start_utc)
            WHERE w.location_id = :location_id AND w.weather_source_id = :weather_source_id
            GROUP BY t.local_date
            HAVING COUNT(w.rainfall_mm) > 0
            ORDER BY t.local_date
            """
        ),
        fact_keys,
    ).all()
    assert rows == [(prior_date, Decimal("2.500"), 1), (LOCAL_DATE, Decimal("0.000"), 1)]


def test_model_results_require_matching_version_kind(db, fact_keys):
    version = db.scalar(
        insert(ModelVersion)
        .values(kind="prediction", model_name=uuid4().hex, version="1")
        .returning(ModelVersion.id)
    )
    result = fact_keys | {
        "model_version_id": version,
        "target_hour_utc": MIDNIGHT_UTC,
        "issued_at": MIDNIGHT_UTC,
    }
    db.execute(insert(PredictionResult).values(result | {"rainfall_mm": Decimal("0.9")}))
    assert_rejected(db, insert(ClassificationResult).values(result | {"label": "test-only"}), "23503")

