from fastapi import FastAPI

from .config import Settings
from .routes.health import router
from .routes.ml import router as ml_router
from .routes.flood_profiles import router as flood_profiles_router


def create_app() -> FastAPI:
    app = FastAPI(title="FloodInsight clustering-service")
    app.state.settings = Settings()
    app.include_router(router)
    app.include_router(ml_router)
    app.include_router(flood_profiles_router)
    return app


app = create_app()
