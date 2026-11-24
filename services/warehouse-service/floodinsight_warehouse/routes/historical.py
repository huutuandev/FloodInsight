from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from ..config import DatabaseSettings
from ..repositories.historical import HistoricalRepository, WarehouseBusy
from ..schemas.historical import (
    BackfillRequest,
    ETLRequest,
    ForecastETLRequest,
    ForecastETLResult,
    QualityReport,
    RunResult,
    WarehouseStatus,
)
from ..services.forecasts import materialize_forecasts
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
def backfill(window: BackfillRequest, request: Request):
    return run_operation(request, "backfill", window)


@router.post("/etl/run", response_model=RunResult)
def etl(window: ETLRequest, request: Request):
    return run_operation(request, "etl", window)


@router.post("/forecast-etl/run", response_model=ForecastETLResult)
def forecast_etl(window: ForecastETLRequest):
    try:
        return materialize_forecasts(window)
    except WarehouseBusy as exc:
        raise HTTPException(409, "Another forecast warehouse operation is running") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc


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

