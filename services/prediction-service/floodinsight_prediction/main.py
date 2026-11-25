from fastapi import FastAPI

from .config import Settings
from .routes.health import router
from .routes.ml import router as ml_router
from .routes.flood_risk import load_config, router as flood_risk_router
from .routes.flood_prediction import router as flood_prediction_router


def create_app() -> FastAPI:
    app = FastAPI(title="FloodInsight prediction-service")
    app.state.settings = Settings()
    app.state.risk_config = load_config(app.state.settings.flood_risk_config)
    app.include_router(router)
    app.include_router(ml_router)
    app.include_router(flood_risk_router)
    app.include_router(flood_prediction_router)
    return app


app = create_app()
