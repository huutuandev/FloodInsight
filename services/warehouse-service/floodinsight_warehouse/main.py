import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import os

from fastapi import FastAPI

from .config import DatabaseSettings, Settings
from .repositories.historical import HistoricalRepository, WarehouseBusy
from .routes.health import router
from .routes.read import router as read_router
from .routes.historical import router as historical_router
from .routes.flood_coverage import router as flood_coverage_router
from .schemas.historical import DateRange, ETLRequest
from .services.pipeline import HistoricalPipeline

logger = logging.getLogger(__name__)


def _run_auto_archive_sync(app: FastAPI) -> None:
    today_utc = datetime.now(timezone.utc).date()
    end_date = today_utc - timedelta(days=5)
    start_date = end_date - timedelta(days=7)
    pipeline = HistoricalPipeline(app.state.settings, HistoricalRepository(DatabaseSettings()))
    try:
        bf = pipeline.run("backfill", DateRange(start_date=start_date, end_date=end_date))
        etl = pipeline.run("etl", ETLRequest(start_date=start_date, end_date=end_date))
        logger.info("Auto ERA5 sync %s..%s completed (backfill=%s, etl=%s)", start_date, end_date, bf.status, etl.status)
    except WarehouseBusy:
        logger.info("Auto ERA5 sync skipped (warehouse busy)")


async def _auto_archive_loop(app: FastAPI, interval_seconds: int) -> None:
    await asyncio.sleep(25)
    while True:
        try:
            await asyncio.to_thread(_run_auto_archive_sync, app)
        except Exception:
            logger.exception("Auto ERA5 archive sync failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    enabled = os.getenv("FLOODINSIGHT_WAREHOUSE_AUTO_SYNC", "true").lower() in ("1", "true", "yes")
    interval = max(1800, int(os.getenv("FLOODINSIGHT_WAREHOUSE_SYNC_INTERVAL_SECONDS", "21600")))
    task = asyncio.create_task(_auto_archive_loop(app, interval)) if enabled else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    app = FastAPI(title="FloodInsight warehouse-service", lifespan=lifespan)
    app.state.settings = Settings()
    app.include_router(router)
    app.include_router(read_router)
    app.include_router(historical_router)
    app.include_router(flood_coverage_router)
    return app


app = create_app()
