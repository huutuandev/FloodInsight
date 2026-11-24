"""PostgreSQL warehouse tables grouped by layer."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(200))
    dataset: Mapped[str] = mapped_column(String(200))
    reference_url: Mapped[str | None] = mapped_column(Text)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("source_id", "run_key"),
        UniqueConstraint("id", "source_id"),
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger"),
        CheckConstraint("records_inserted >= 0", name="record_count"),
        Index("ix_ingestion_runs_source_history", "source_id", "id"),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL "
            "AND finished_at >= started_at)",
            name="lifecycle",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    run_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'running'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str | None] = mapped_column(String(16))
    records_inserted: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawWeatherRecord:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger)
    ingestion_run_id: Mapped[int] = mapped_column(BigInteger)
    source_location_key: Mapped[str] = mapped_column(String(200))
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawWeatherObservation(RawWeatherRecord, Base):
    __tablename__ = "raw_weather_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ingestion_run_id", "source_id"], ["ingestion_runs.id", "ingestion_runs.source_id"]
        ),
        UniqueConstraint("source_id", "source_location_key", "valid_at"),
        Index("ix_raw_weather_observations_run", "ingestion_run_id", "source_id"),
        CheckConstraint("isfinite(valid_at)", name="valid_instant"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
    )


class RawWeatherForecast(RawWeatherRecord, Base):
    __tablename__ = "raw_weather_forecasts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ingestion_run_id", "source_id"], ["ingestion_runs.id", "ingestion_runs.source_id"]
        ),
        UniqueConstraint("source_id", "source_location_key", "valid_at", "issued_at"),
        Index("ix_raw_weather_forecasts_run", "ingestion_run_id", "source_id"),
        Index(
            "uq_raw_weather_forecasts_snapshot",
            "source_id", "source_location_key", "valid_at", "snapshot_hash",
            unique=True,
            postgresql_where=text("snapshot_hash IS NOT NULL"),
        ),
        Index(
            "ix_raw_weather_forecasts_current",
            "source_id", "source_location_key", "valid_at", "received_at",
            postgresql_where=text("payload ->> 'kind' = 'current'"),
        ),
        CheckConstraint(
            "isfinite(valid_at) AND ("
            "(issued_at IS NOT NULL AND isfinite(issued_at) AND issued_at <= valid_at "
            "AND snapshot_hash IS NULL) OR "
            "(issued_at IS NULL AND snapshot_hash IS NOT NULL "
            "AND snapshot_hash ~ '^[0-9a-f]{64}$'))",
            name="snapshot_or_issue",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
    )

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))


class DimDate(Base):
    __tablename__ = "dim_date"
    __table_args__ = (CheckConstraint("isfinite(local_date)", name="finite_date"),)

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)


class DimTime(Base):
    __tablename__ = "dim_time"
    __table_args__ = (
        CheckConstraint(
            "isfinite(hour_start_utc) AND "
            "date_trunc('hour', hour_start_utc AT TIME ZONE 'UTC') = hour_start_utc AT TIME ZONE 'UTC'",
            name="utc_hour_boundary",
        ),
        Index("ix_dim_time_local_date_hour", "local_date", "hour_start_utc"),
    )

    hour_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    local_date: Mapped[date] = mapped_column(
        Date,
        ForeignKey("dim_date.local_date"),
        Computed("(hour_start_utc AT TIME ZONE 'Asia/Ho_Chi_Minh')::date", persisted=True),
    )
    local_hour: Mapped[int] = mapped_column(
        SmallInteger,
        Computed("EXTRACT(HOUR FROM hour_start_utc AT TIME ZONE 'Asia/Ho_Chi_Minh')", persisted=True),
    )


class DimLocation(Base):
    __tablename__ = "dim_location"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))


class DimWeatherSource(Base):
    __tablename__ = "dim_weather_source"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))


class WeatherMeasurements:
    rainfall_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    air_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    relative_humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    wind_speed_mps: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))


# Each mapping needs its own SQLAlchemy constraint objects.
def weather_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("rainfall_mm >= 0 AND rainfall_mm <> 'NaN'::numeric", name="rainfall"),
        CheckConstraint("air_temperature_c <> 'NaN'::numeric", name="finite_temperature"),
        CheckConstraint("relative_humidity_pct BETWEEN 0 AND 100", name="humidity"),
        CheckConstraint("wind_speed_mps >= 0 AND wind_speed_mps <> 'NaN'::numeric", name="wind"),
        CheckConstraint(
            "num_nonnulls(rainfall_mm, air_temperature_c, relative_humidity_pct, wind_speed_mps) > 0",
            name="has_measurement",
        ),
    )


class WeatherFactKeys:
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.id"), primary_key=True)
    weather_source_id: Mapped[int] = mapped_column(
        ForeignKey("dim_weather_source.id"), primary_key=True
    )


class HourlyWeatherFactKeys(WeatherFactKeys):
    hour_start_utc: Mapped[datetime] = mapped_column(
        ForeignKey("dim_time.hour_start_utc"), primary_key=True
    )


class FactWeatherHourly(HourlyWeatherFactKeys, WeatherMeasurements, Base):
    __tablename__ = "fact_weather_hourly"
    __table_args__ = (
        PrimaryKeyConstraint("location_id", "weather_source_id", "hour_start_utc"),
        Index("ix_fact_weather_hourly_hour", "hour_start_utc"),
        *weather_checks(),
    )


class FactWeatherForecastHourly(WeatherMeasurements, Base):
    __tablename__ = "fact_weather_forecast_hourly"
    __table_args__ = (
        Index("ix_fact_weather_forecast_hourly_hour", "hour_start_utc", "issued_at"),
        Index("ix_fact_weather_forecast_hourly_snapshot", "hour_start_utc", "snapshot_received_at"),
        Index(
            "uq_fact_weather_forecast_hourly_issued",
            "location_id", "weather_source_id", "hour_start_utc", "issued_at",
            unique=True,
            postgresql_where=text("issued_at IS NOT NULL"),
        ),
        Index(
            "uq_fact_weather_forecast_hourly_snapshot",
            "location_id", "weather_source_id", "hour_start_utc", "snapshot_received_at",
            unique=True,
            postgresql_where=text("issued_at IS NULL"),
        ),
        CheckConstraint(
            "(issued_at IS NOT NULL AND isfinite(issued_at) AND issued_at <= hour_start_utc "
            "AND snapshot_received_at IS NULL) OR "
            "(issued_at IS NULL AND snapshot_received_at IS NOT NULL "
            "AND isfinite(snapshot_received_at))",
            name="forecast_identity",
        ),
        *weather_checks(),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.id"), nullable=False)
    weather_source_id: Mapped[int] = mapped_column(
        ForeignKey("dim_weather_source.id"), nullable=False
    )
    hour_start_utc: Mapped[datetime] = mapped_column(
        ForeignKey("dim_time.hour_start_utc"), nullable=False
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FactRainfallDaily(WeatherFactKeys, Base):
    __tablename__ = "fact_rainfall_daily"
    __table_args__ = (
        PrimaryKeyConstraint("location_id", "weather_source_id", "local_date"),
        Index("ix_fact_rainfall_daily_date", "local_date"),
        CheckConstraint(
            "rainfall_total_mm >= 0 AND rainfall_total_mm <> 'NaN'::numeric", name="rainfall"
        ),
        CheckConstraint("hours_with_rainfall BETWEEN 1 AND 26", name="hour_count"),
    )

    local_date: Mapped[date] = mapped_column(ForeignKey("dim_date.local_date"), primary_key=True)
    rainfall_total_mm: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    hours_with_rainfall: Mapped[int] = mapped_column(SmallInteger)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("kind", "model_name", "version"),
        UniqueConstraint("id", "kind"),
        CheckConstraint("jsonb_typeof(training_metadata) = 'object'", name="training_metadata_object"),
        CheckConstraint("kind IN ('clustering', 'prediction', 'classification')", name="kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    model_name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(80))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    training_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsResult:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("dim_location.id"))
    weather_source_id: Mapped[int] = mapped_column(ForeignKey("dim_weather_source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WindowedResult(AnalyticsResult):
    window_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HourlyModelResult(AnalyticsResult):
    target_hour_utc: Mapped[datetime] = mapped_column(ForeignKey("dim_time.hour_start_utc"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def model_checks(kind: str) -> tuple[ForeignKeyConstraint, CheckConstraint]:
    return (
        ForeignKeyConstraint(
            ["model_version_id", "model_kind"], ["model_versions.id", "model_versions.kind"]
        ),
        CheckConstraint(f"model_kind = '{kind}'", name="model_kind"),
    )


class AnalysisResult(WindowedResult, Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint(
            "analysis_key", "location_id", "weather_source_id", "window_start_utc", "window_end_utc"
        ),
        Index("ix_analysis_results_location_window", "location_id", "window_start_utc"),
        CheckConstraint(
            "isfinite(window_start_utc) AND isfinite(window_end_utc) "
            "AND window_start_utc < window_end_utc",
            name="window_order",
        ),
        CheckConstraint("jsonb_typeof(result) = 'object'", name="result_object"),
    )

    analysis_key: Mapped[str] = mapped_column(String(200))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ClusteringResult(WindowedResult, Base):
    __tablename__ = "clustering_results"
    __table_args__ = (
        *model_checks("clustering"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        UniqueConstraint(
            "model_version_id", "location_id", "weather_source_id", "window_start_utc", "window_end_utc"
        ),
        Index("ix_clustering_results_location_window", "location_id", "window_start_utc"),
        CheckConstraint(
            "isfinite(window_start_utc) AND isfinite(window_end_utc) "
            "AND window_start_utc < window_end_utc",
            name="window_order",
        ),
    )

    model_version_id: Mapped[int] = mapped_column(BigInteger)
    model_kind: Mapped[str] = mapped_column(String(16), server_default=text("'clustering'"))
    cluster_label: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class PredictionResult(HourlyModelResult, Base):
    __tablename__ = "prediction_results"
    __table_args__ = (
        *model_checks("prediction"),
        UniqueConstraint(
            "model_version_id", "location_id", "weather_source_id", "target_hour_utc", "issued_at"
        ),
        Index("ix_prediction_results_location_hour", "location_id", "target_hour_utc"),
        CheckConstraint("isfinite(issued_at) AND issued_at <= target_hour_utc", name="issue_time"),
        CheckConstraint("rainfall_mm >= 0 AND rainfall_mm <> 'NaN'::numeric", name="rainfall"),
    )

    model_version_id: Mapped[int] = mapped_column(BigInteger)
    model_kind: Mapped[str] = mapped_column(String(16), server_default=text("'prediction'"))
    rainfall_mm: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class ClassificationResult(HourlyModelResult, Base):
    __tablename__ = "classification_results"
    __table_args__ = (
        *model_checks("classification"),
        CheckConstraint("jsonb_typeof(probabilities) = 'object'", name="probabilities_object"),
        UniqueConstraint(
            "model_version_id", "location_id", "weather_source_id", "target_hour_utc", "issued_at"
        ),
        Index("ix_classification_results_location_hour", "location_id", "target_hour_utc"),
        CheckConstraint("isfinite(issued_at)", name="issue_time"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
    )

    model_version_id: Mapped[int] = mapped_column(BigInteger)
    model_kind: Mapped[str] = mapped_column(String(16), server_default=text("'classification'"))
    label: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class WarehouseRun(Base):
    __tablename__ = "warehouse_runs"
    __table_args__ = (
        CheckConstraint("operation IN ('backfill', 'etl')", name="operation"),
        CheckConstraint("end_date >= start_date", name="dates"),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL "
            "AND finished_at >= started_at)",
            name="lifecycle",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    operation: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)


class HistoricalBatch(Base):
    __tablename__ = "historical_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ingestion_run_id", "source_id"], ["ingestion_runs.id", "ingestion_runs.source_id"]
        ),
        UniqueConstraint("source_id", "location_code", "start_date", "end_date"),
        CheckConstraint("end_date >= start_date", name="dates"),
        CheckConstraint("(etl_run_id IS NULL) = (quality IS NULL)", name="quality"),
        Index("ix_historical_batches_date_range", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    location_code: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    ingestion_run_id: Mapped[int] = mapped_column(BigInteger)
    backfill_run_id: Mapped[int] = mapped_column(ForeignKey("warehouse_runs.id"))
    etl_run_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_runs.id"))
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
