import asyncio
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI

from floodinsight_ml.daily import NextDayRequest, inference_input
from floodinsight_ml.daily_results import save_next_day
from floodinsight_ml.storage import Models, connect

from .config import Settings
from .routes.health import router
from .routes.ml import router as ml_router
from .services.classifier import Thresholds, calibrate_classification, predict_class

logger = logging.getLogger(__name__)


def _run_auto_classification(app: FastAPI) -> None:
    with connect() as conn:
        locations = [row["code"] for row in conn.execute("SELECT code FROM dim_location ORDER BY code")]
    model, artifact = Models("classification", "next-day-rainfall-classifier", app.state.settings.artifact_dir).load(None)
    thresholds = Thresholds(**model["training_metadata"]["scope"].get("thresholds", {}))
    updated = 0
    for loc_code in locations:
        try:
            payload = NextDayRequest(location=loc_code)
            target, issued, location, features = inference_input(payload, model)
            raw_label, raw_probabilities = predict_class(artifact, features)
            label, probabilities = calibrate_classification(loc_code, target, raw_label, raw_probabilities, thresholds)
            save_next_day("classification", model["id"], target, issued, location, label, probabilities)
            updated += 1
        except Exception as exc:
            logger.warning("Auto-classification skipped for %s: %s", loc_code, exc)
    logger.info("Auto-refresh XGBoost rainfall classification completed for %d locations", updated)


async def _auto_refresh_loop(app: FastAPI, interval_seconds: int) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await asyncio.to_thread(_run_auto_classification, app)
        except Exception as exc:
            logger.info("Auto-classification deferred: %s", exc)
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    enabled = os.getenv("FLOODINSIGHT_CLASSIFICATION_AUTO_REFRESH", "true").lower() in ("1", "true", "yes")
    interval = max(300, int(os.getenv("FLOODINSIGHT_CLASSIFICATION_INTERVAL_SECONDS", "3600")))
    task = asyncio.create_task(_auto_refresh_loop(app, interval)) if enabled else None
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
    app = FastAPI(title="FloodInsight classification-service", lifespan=lifespan)
    app.state.settings = Settings()
    app.include_router(router)
    app.include_router(ml_router)
    return app


app = create_app()
