"""Coverage inventory for the flood dashboard."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ..config import DatabaseSettings
from ..flood_data import audit

router = APIRouter(prefix="/warehouse/flood-data", tags=["flood coverage"])


class Coverage(BaseModel):
    weather_daily: list[dict]
    weather_hourly_nulls: list[dict]
    historical_batch_quality: list[dict]
    weather_provider_grids: list[dict]
    assets: list[dict]
    events: list[dict]
    labels: list[dict]
    terrain: list[dict]
    hydrology: list[dict]
    counts: dict[str, int]
    label_counts: dict[str, int]


@router.get("/coverage", response_model=Coverage)
def coverage():
    engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as conn:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '8s'"))
            report = audit(conn)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Flood coverage unavailable") from exc
    finally:
        engine.dispose()
    report["label_counts"] = {label: sum(row["rows"] for row in report["labels"] if row["label"] == label)
                              for label in ("flood_confirmed", "non_flood_confirmed", "unknown")}
    return report
