from fastapi import FastAPI

from .config import Settings
from .routes.health import router


def create_app() -> FastAPI:
    app = FastAPI(title="FloodInsight classification-service")
    app.state.settings = Settings()
    app.include_router(router)
    return app


app = create_app()
