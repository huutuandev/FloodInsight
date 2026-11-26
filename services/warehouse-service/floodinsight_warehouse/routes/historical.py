from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ..config import DatabaseSettings
from ..flood_data import save
from ..services.flood_sources import POINTS, collect
from ..repositories.historical import HistoricalRepository, WarehouseBusy
from ..schemas.historical import DateRange, ETLRequest, QualityReport, RunResult, WarehouseStatus
from ..services.pipeline import HistoricalPipeline

router = APIRouter(prefix="/warehouse", tags=["historical warehouse"])


def run_operation(request: Request, operation, window):
    try:
        pipeline = HistoricalPipeline(request.app.state.settings, HistoricalRepository(DatabaseSettings()))
        return pipeline.run(operation, window)
    except WarehouseBusy as exc:
        raise HTTPException(409, "Another warehouse operation is running") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc


@router.post("/backfill", response_model=RunResult)
def backfill(window: DateRange, request: Request):
    return run_operation(request, "backfill", window)


@router.post("/etl/run", response_model=RunResult)
def etl(window: ETLRequest, request: Request):
    return run_operation(request, "etl", window)


@router.post("/flood-soil/refresh", include_in_schema=False)
def refresh_delayed_soil():
    day = datetime.now(timezone.utc).date() - timedelta(days=6)
    engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as conn:
            if not conn.scalar(text("SELECT pg_try_advisory_xact_lock(5065502657771540303)")):
                return {"status": "busy", "date": day}
            covered = conn.scalar(text("""
                SELECT count(*) FROM (
                    SELECT l.code FROM flood_hydrology_observations h
                    JOIN flood_dataset_assets a ON a.id = h.asset_id
                    JOIN data_sources d ON d.id = a.source_id
                    JOIN dim_location l ON l.id = h.location_id
                    WHERE d.code = 'open-meteo-archive-era5' AND h.variable = 'soil_moisture_0_to_7cm'
                      AND h.valid_at >= CAST(:day AS timestamp) AT TIME ZONE 'UTC'
                      AND h.valid_at < (CAST(:day AS timestamp) + interval '1 day') AT TIME ZONE 'UTC'
                      AND l.code = ANY(:points)
                    GROUP BY l.code HAVING count(DISTINCT h.valid_at) = 24
                ) complete
            """), {"day": day, "points": [point.code for point in POINTS]})
            if covered == len(POINTS):
                return {"status": "already_collected", "date": day}
            with httpx.Client(timeout=10) as client:
                batches = list(collect(client, "soil-moisture", day, day))
            return {"status": "collected", "date": day, "inserted": save(conn, batches)}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "ERA5 soil moisture is unavailable") from exc
    finally:
        engine.dispose()


@router.get("/status", response_model=WarehouseStatus)
def status(limit: Annotated[int, Query(ge=1, le=100)] = 20):
    try:
        return HistoricalRepository(DatabaseSettings()).status(limit)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc


@router.get("/quality", response_model=list[QualityReport])
def quality(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    try:
        return HistoricalRepository(DatabaseSettings()).quality(limit, offset)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc

