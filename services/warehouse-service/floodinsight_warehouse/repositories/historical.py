from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.pool import NullPool

from ..config import DatabaseSettings
from ..services.historical import DAY, POINTS, utc_bounds
from ..services.transform import transform_hours
from .models import (
    DataSource,
    DimDate,
    DimLocation,
    DimTime,
    DimWeatherSource,
    FactRainfallDaily,
    FactWeatherHourly,
    HistoricalBatch,
    IngestionRun,
    RawWeatherObservation,
    WarehouseRun,
)

SOURCE_CODE = "open-meteo-archive-era5"
LOCK_KEY = 0x464C4F4F4445544C


class WarehouseBusy(Exception):
    pass


class HistoricalRepository:
    def __init__(self, settings: DatabaseSettings):
        self.engine = create_engine(settings.url(), poolclass=NullPool, connect_args={"connect_timeout": 5})

    @contextmanager
    def exclusive(self):
        with self.engine.connect() as conn:
            if not conn.scalar(select(func.pg_try_advisory_lock(LOCK_KEY))):
                raise WarehouseBusy
            conn.commit()
            # NullPool closes the dedicated session and releases the lock on all exits.
            yield conn

    def start(self, conn, operation, window):
        with conn.begin():
            conn.execute(
                update(WarehouseRun)
                .where(WarehouseRun.status == "running")
                .values(status="failed", finished_at=func.greatest(func.clock_timestamp(), WarehouseRun.started_at),
                        error_message="Worker was interrupted")
            )
            conn.execute(
                pg_insert(DataSource)
                .values(code=SOURCE_CODE, provider="Open-Meteo", dataset="Historical Weather ERA5",
                        reference_url="https://open-meteo.com/en/docs/historical-weather-api")
                .on_conflict_do_nothing(index_elements=["code"])
            )
            source_id = conn.scalar(select(DataSource.id).where(DataSource.code == SOURCE_CODE))
            conn.execute(
                update(IngestionRun)
                .where(IngestionRun.status == "running", IngestionRun.source_id == source_id)
                .values(status="failed", finished_at=func.greatest(func.clock_timestamp(), IngestionRun.started_at),
                        error_message="Historical worker was interrupted")
            )
            run_id = conn.scalar(
                insert(WarehouseRun).values(
                    operation=operation, start_date=window.start_date, end_date=window.end_date,
                    status="running", progress={},
                ).returning(WarehouseRun.id)
            )
            ingestion_id = None
            if operation == "backfill":
                ingestion_id = conn.scalar(
                    insert(IngestionRun)
                    .values(source_id=source_id, run_key=uuid4().hex, trigger="manual")
                    .returning(IngestionRun.id)
                )
        return source_id, run_id, ingestion_id

    def checkpoints(self, conn, source_id, window):
        with conn.begin():
            return conn.execute(
                select(HistoricalBatch.__table__).where(
                    HistoricalBatch.source_id == source_id,
                    HistoricalBatch.start_date >= window.start_date,
                    HistoricalBatch.end_date <= window.end_date,
                    HistoricalBatch.location_code.in_(window.locations)
                    if window.locations is not None else text("TRUE"),
                ).order_by(HistoricalBatch.id)
            ).mappings().all()

    def save_batch(self, conn, source_id, run_id, ingestion_id, point, start, end, records, progress):
        with conn.begin():
            raw = RawWeatherObservation.__table__
            rows = [
                dict(source_id=source_id, ingestion_run_id=ingestion_id, source_location_key=point.code,
                     valid_at=row.valid_at, received_at=row.received_at, payload=row.payload)
                for row in records
            ]
            statement = pg_insert(raw).on_conflict_do_nothing(
                index_elements=["source_id", "source_location_key", "valid_at"]
            ).returning(raw.c.id)
            inserted = len(conn.scalars(statement, rows).all())
            conn.execute(insert(HistoricalBatch).values(
                source_id=source_id, location_code=point.code, start_date=start, end_date=end,
                ingestion_run_id=ingestion_id, backfill_run_id=run_id,
            ))
            progress = progress | {
                "batches_processed": progress["batches_processed"] + 1,
                "remaining_batches": progress["remaining_batches"] - 1,
                "raw_rows_inserted": progress["raw_rows_inserted"] + inserted,
            }
            self.save_progress(conn, run_id, progress)
            conn.execute(update(IngestionRun).where(IngestionRun.id == ingestion_id)
                         .values(records_inserted=progress["raw_rows_inserted"]))
        return progress

    def load_batch(self, conn, run_id, batch, progress):
        lower, upper = utc_bounds(batch["start_date"], batch["end_date"])
        point = next(point for point in POINTS if point.code == batch["location_code"])
        source_id = batch["source_id"]
        with conn.begin():
            raw_rows = conn.execute(
                select(RawWeatherObservation.valid_at, RawWeatherObservation.payload).where(
                    RawWeatherObservation.source_id == source_id,
                    RawWeatherObservation.source_location_key == point.code,
                    RawWeatherObservation.valid_at.between(lower, upper),
                )
            )
            hourly, report = transform_hours(
                {valid_at: payload["values"] for valid_at, payload in raw_rows}, lower, upper
            )
            location_id, weather_source_id = dimension_keys(conn, point, source_id)
            start, end = batch["start_date"], batch["end_date"]
            days = [{"local_date": start + index * DAY} for index in range((end - start).days + 1)]
            conn.execute(pg_insert(DimDate).on_conflict_do_nothing(), days)

            conn.execute(delete(FactWeatherHourly).where(
                FactWeatherHourly.location_id == location_id,
                FactWeatherHourly.weather_source_id == weather_source_id,
                FactWeatherHourly.hour_start_utc >= lower,
                FactWeatherHourly.hour_start_utc < upper,
            ))
            if hourly:
                conn.execute(pg_insert(DimTime).on_conflict_do_nothing(),
                             [{"hour_start_utc": row["hour_start_utc"]} for row in hourly])
                keys = {"location_id": location_id, "weather_source_id": weather_source_id}
                conn.execute(insert(FactWeatherHourly), [keys | row for row in hourly])
            replace_daily(conn, location_id, weather_source_id, start, end)
            conn.execute(update(HistoricalBatch).where(HistoricalBatch.id == batch["id"])
                         .values(etl_run_id=run_id, quality=report))
            progress = progress | {
                "batches_processed": progress["batches_processed"] + 1,
                "remaining_batches": progress["remaining_batches"] - 1,
                "hourly_rows_loaded": progress["hourly_rows_loaded"] + len(hourly),
                "last_batch_id": batch["id"],
            }
            self.save_progress(conn, run_id, progress)
        return progress

    def save_progress(self, conn, run_id, progress):
        conn.execute(update(WarehouseRun).where(WarehouseRun.id == run_id).values(progress=progress))

    def finish(self, conn, run_id, ingestion_id, progress, error):
        status = "failed" if error else "succeeded"
        with conn.begin():
            if ingestion_id is not None:
                conn.execute(update(IngestionRun).where(IngestionRun.id == ingestion_id).values(
                    status=status, finished_at=func.greatest(func.clock_timestamp(), IngestionRun.started_at),
                    records_inserted=progress.get("raw_rows_inserted", 0), error_message=error,
                ))
            return dict(conn.execute(
                update(WarehouseRun).where(WarehouseRun.id == run_id).values(
                    status=status, finished_at=func.greatest(func.clock_timestamp(), WarehouseRun.started_at),
                    progress=progress, error_message=error,
                ).returning(WarehouseRun.__table__)
            ).mappings().one())

    def status(self, limit):
        with self.engine.connect() as conn:
            runs = conn.execute(
                select(WarehouseRun.__table__).order_by(WarehouseRun.id.desc()).limit(limit)
            ).mappings().all()
            total, processed = conn.execute(select(func.count(HistoricalBatch.id),
                                                 func.count(HistoricalBatch.etl_run_id))).one()
        return {"runs": runs, "downloaded_batches": total, "loaded_batches": processed}

    def quality(self, limit, offset):
        with self.engine.connect() as conn:
            return conn.execute(select(
                HistoricalBatch.id, HistoricalBatch.location_code, HistoricalBatch.start_date,
                HistoricalBatch.end_date, HistoricalBatch.etl_run_id, HistoricalBatch.quality,
            ).where(HistoricalBatch.etl_run_id.is_not(None))
             .order_by(HistoricalBatch.etl_run_id.desc(), HistoricalBatch.id.desc())
             .limit(limit).offset(offset)).mappings().all()


def dimension_keys(conn, point, source_id):
    conn.execute(pg_insert(DimLocation).values(
        code=point.code, name=point.name, latitude=point.latitude, longitude=point.longitude
    ).on_conflict_do_nothing(index_elements=["code"]))
    conn.execute(pg_insert(DimWeatherSource).values(
        data_source_id=source_id, name="Open-Meteo ERA5 historical reanalysis"
    ).on_conflict_do_nothing(index_elements=["data_source_id"]))
    location_id = conn.scalar(select(DimLocation.id).where(DimLocation.code == point.code))
    weather_source_id = conn.scalar(select(DimWeatherSource.id)
                                    .where(DimWeatherSource.data_source_id == source_id))
    return location_id, weather_source_id


def replace_daily(conn, location_id, weather_source_id, start, end):
    conn.execute(delete(FactRainfallDaily).where(
        FactRainfallDaily.location_id == location_id,
        FactRainfallDaily.weather_source_id == weather_source_id,
        FactRainfallDaily.local_date.between(start, end),
    ))
    conn.execute(text("""
        INSERT INTO fact_rainfall_daily
            (location_id, weather_source_id, local_date, rainfall_total_mm, hours_with_rainfall)
        SELECT w.location_id, w.weather_source_id, t.local_date,
               sum(w.rainfall_mm), count(w.rainfall_mm)
        FROM fact_weather_hourly w JOIN dim_time t USING (hour_start_utc)
        WHERE w.location_id = :location AND w.weather_source_id = :source
          AND t.local_date BETWEEN :start AND :end
        GROUP BY w.location_id, w.weather_source_id, t.local_date
        HAVING count(w.rainfall_mm) > 0
    """), dict(location=location_id, source=weather_source_id, start=start, end=end))

