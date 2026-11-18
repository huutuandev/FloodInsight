from fastapi import FastAPI

from .config import Settings
from .routes.health import router
from .routes.patterns import router as patterns_router


def create_app() -> FastAPI:
    app = FastAPI(title="FloodInsight analysis-service")
    app.state.settings = Settings()
    app.include_router(router)
    app.include_router(patterns_router)
    return app


app = create_app()
