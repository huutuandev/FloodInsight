from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ..config import DatabaseSettings

from ..schemas.health import HealthResponse

router = APIRouter(tags=["operations"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(service="warehouse-service")

@router.get("/ready")
def ready():
    engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(503, "Warehouse database unavailable") from error
    finally:
        engine.dispose()
    return {"status": "ok", "service": "postgres"}
