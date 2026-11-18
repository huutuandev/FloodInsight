from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from ..repositories.ingestion import IngestionBusy
from ..schemas.ingestion import IngestionStatus, LatestSnapshot, RunSummary
from ..services.ingestion import JOB_ID

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/run", response_model=RunSummary, responses={409: {}, 502: {}, 503: {}})
async def run_ingestion(request: Request) -> RunSummary:
    try:
        run = await request.app.state.ingestion.run("manual")
    except IngestionBusy as error:
        raise HTTPException(409, "Ingestion is already running") from error
    except psycopg.Error as error:
        raise HTTPException(503, "Warehouse is unavailable") from error
    if run.status == "failed":
        raise HTTPException(502, detail=run.model_dump(mode="json"))
    return run


@router.get("/status")
async def ingestion_status(request: Request) -> IngestionStatus:
    state = request.app.state
    try:
        runs = await state.ingestion.repository.history(1, 0)
    except psycopg.Error as error:
        raise HTTPException(503, "Warehouse is unavailable") from error
    job = state.scheduler.get_job(JOB_ID)
    return IngestionStatus(
        scheduler_enabled=state.settings.scheduler_enabled,
        interval_seconds=state.settings.interval_seconds,
        next_run_at=job.next_run_time if job else None,
        latest_run=runs[0] if runs else None,
    )


@router.get("/latest")
async def latest_ingestion(request: Request) -> list[LatestSnapshot]:
    try:
        return await request.app.state.ingestion.repository.latest()
    except psycopg.Error as error:
        raise HTTPException(503, "Warehouse is unavailable") from error


@router.get("/history")
async def ingestion_history(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    try:
        return await request.app.state.ingestion.repository.history(limit, offset)
    except psycopg.Error as error:
        raise HTTPException(503, "Warehouse is unavailable") from error
