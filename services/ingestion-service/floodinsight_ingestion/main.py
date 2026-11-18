from contextlib import asynccontextmanager

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from .config import Settings
from .repositories.ingestion import IngestionRepository
from .routes.health import router as health_router
from .routes.ingestion import router as ingestion_router
from .services.ingestion import JOB_ID, IngestionService
from .services.open_meteo import OpenMeteoClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as http:
        ingestion = IngestionService(IngestionRepository(), OpenMeteoClient(http, settings))
        scheduler = AsyncIOScheduler(timezone="UTC")
        app.state.ingestion = ingestion
        app.state.scheduler = scheduler
        if settings.scheduler_enabled:
            scheduler.add_job(
                ingestion.scheduled_run,
                "interval",
                seconds=settings.interval_seconds,
                id=JOB_ID,
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
        try:
            yield
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=False)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="FloodInsight ingestion-service", lifespan=lifespan)
    app.state.settings = settings or Settings()
    app.include_router(health_router)
    app.include_router(ingestion_router)
    return app


app = create_app()
