import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import os

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder

from floodinsight_ml.daily import NextDayRequest, inference_input
from floodinsight_ml.daily_results import save_next_day
from floodinsight_ml.flood_risk import assess, digest, sensitivity
from floodinsight_ml.flood_store import current_features, resolve_issuance
from floodinsight_ml.storage import Models, connect

from .config import Settings
from .routes.health import router
from .routes.ml import router as ml_router
from .routes.flood_risk import load_config, router as flood_risk_router, store_assessment
from .routes.flood_prediction import router as flood_prediction_router
from .services.regression import calibrate_prediction

logger = logging.getLogger(__name__)


def _run_auto_cycle(app: FastAPI) -> None:
    config = app.state.risk_config
    issuance = resolve_issuance(None)
    # 1. Auto-generate operational flood-risk assessments for all 9 Da Nang locations
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        locations = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM dim_location")}
        results = [
            (locations[row["location"]], jsonable_encoder(assess(row, config) | {"sensitivity": sensitivity(row, config)}))
            for row in current_features(conn, issuance)
        ]
    config_json = config.model_dump(mode="json")
    with connect() as conn:
        for location_id, result in results:
            store_assessment(conn, (location_id, issuance, config.version, digest(result)), result, config_json)
    logger.info("Auto-refresh flood risk assessments completed for %d locations (issuance=%s)", len(results), issuance.isoformat())

    # 2. Auto-run XGBoost rainfall predictions for both today ICT and tomorrow ICT
    try:
        model, artifact = Models("prediction", "next-day-rainfall-regressor", app.state.settings.artifact_dir).load(None)
        today_ict = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
        target_dates = [today_ict, today_ict + timedelta(days=1)]
        updated = 0
        for t_date in target_dates:
            for loc_code in sorted(locations):
                try:
                    payload = NextDayRequest(location=loc_code, target_date=t_date)
                    target, issued, location, features = inference_input(payload, model)
                    raw_value = float(artifact.predict(features)[0])
                    calibrated_value = calibrate_prediction(loc_code, target, raw_value)
                    save_next_day("prediction", model["id"], target, issued, location, calibrated_value)
                    updated += 1
                except Exception as exc:
                    logger.warning("Auto-prediction skipped for %s (%s): %s", loc_code, t_date, exc)
        logger.info("Auto-refresh XGBoost rainfall predictions completed (%d records)", updated)
    except Exception as exc:
        logger.info("Auto-prediction deferred (no active model or data): %s", exc)


async def _auto_refresh_loop(app: FastAPI, interval_seconds: int) -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await asyncio.to_thread(_run_auto_cycle, app)
        except Exception:
            logger.exception("Auto-refresh cycle failed in prediction-service")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    enabled = os.getenv("FLOODINSIGHT_PREDICTION_AUTO_REFRESH", "true").lower() in ("1", "true", "yes")
    interval = max(60, int(os.getenv("FLOODINSIGHT_PREDICTION_INTERVAL_SECONDS", "900")))
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
    app = FastAPI(title="FloodInsight prediction-service", lifespan=lifespan)
    app.state.settings = Settings()
    app.state.risk_config = load_config(app.state.settings.flood_risk_config)
    app.include_router(router)
    app.include_router(ml_router)
    app.include_router(flood_risk_router)
    app.include_router(flood_prediction_router)
    return app


app = create_app()
