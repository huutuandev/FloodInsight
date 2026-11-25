"""Versioned experimental flood assessments and their stored evidence."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, Field

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.flood_risk import RiskConfig, assess, digest, sensitivity
from floodinsight_ml.flood_store import current_features, resolve_issuance
from floodinsight_ml.storage import DataUnavailable, connect

router = APIRouter(prefix="/flood-risk", tags=["experimental flood risk"])
Location = Annotated[str, Field(min_length=1, max_length=100)]


class RiskRequest(BaseModel):
    location: Location
    issued_at: AwareDatetime | None = None


class GenerateRequest(BaseModel):
    location: Location | None = None
    issued_at: AwareDatetime | None = None


class Point(BaseModel):
    code: str
    name: str
    latitude: float
    longitude: float


class Assessment(BaseModel, extra="allow"):
    id: int
    location: str
    issued_at: datetime
    valid_until: datetime
    created_at: datetime
    risk_category: Literal["Low", "Moderate", "High", "Very High", "Insufficient Data"]
    risk_index: float | None
    flood_probability: None = None
    forecast_horizon_hours: int
    method_version: str
    assessment_status: str
    validation_status: str
    weight_coverage: float
    missing_features: list[str]


class PointAssessment(BaseModel):
    point: Point
    assessment: Assessment | None
    is_current: bool


@router.post("/assessments")
@warehouse_errors
def create_assessment(payload: RiskRequest, request: Request):
    return generate(payload, request)[0]


@router.post("/generate", response_model=list[Assessment])
@warehouse_errors
def generate(payload: GenerateRequest, request: Request):
    try:
        issuance = resolve_issuance(payload.issued_at)
    except ValueError as exc:
        raise DataUnavailable(str(exc)) from exc
    config = request.app.state.risk_config
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        locations = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM dim_location")}
        if payload.location is not None and payload.location not in locations:
            raise HTTPException(404, "Unknown monitoring point")
        results = [
            (locations[row["location"]], jsonable_encoder(assess(row, config) | {"sensitivity": sensitivity(row, config)}))
            for row in current_features(conn, issuance) if payload.location is None or row["location"] == payload.location
        ]
    config_json = config.model_dump(mode="json")
    # The evidence read has a fixed snapshot. Use a fresh transaction for concurrent replay.
    with connect() as conn:
        return [store_assessment(conn, (location_id, issuance, config.version, digest(result)), result, config_json)
                for location_id, result in results]


def store_assessment(conn, key, result, config_json):
    stored = conn.execute("""
            INSERT INTO flood_risk_assessments
                (location_id, issued_at, method_version, evidence_sha256, feature_version,
                 horizon_hours, risk_index, risk_category, result, configuration)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (location_id, issued_at, method_version, evidence_sha256) DO NOTHING
            RETURNING id, created_at
        """, (*key, result["feature_version"], result["forecast_horizon_hours"], result["risk_index"],
              result["risk_category"], Jsonb(result), Jsonb(config_json))).fetchone()
    if stored is None:
        stored = conn.execute("""
                SELECT id, created_at FROM flood_risk_assessments
                WHERE location_id = %s AND issued_at = %s AND method_version = %s AND evidence_sha256 = %s
            """, key).fetchone()
    return result | {"id": stored["id"], "created_at": stored["created_at"],
                     "valid_until": key[1] + timedelta(hours=result["forecast_horizon_hours"])}


@router.get("/assessments")
@router.get("/history", response_model=list[Assessment])
@warehouse_errors
def assessments(location: Annotated[Location | None, Query()] = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 20):
    with connect() as conn:
        rows = conn.execute("""
            SELECT a.id, a.created_at, a.result,
                   a.issued_at + a.horizon_hours * interval '1 hour' AS valid_until FROM flood_risk_assessments a
            JOIN dim_location l ON a.location_id = l.id
            WHERE (%s::text IS NULL OR l.code = %s) ORDER BY a.issued_at DESC, a.id DESC LIMIT %s
        """, (location, location, limit)).fetchall()
    return [stored_result(row) for row in rows]


def stored_result(row):
    return row["result"] | {key: row[key] for key in ("id", "created_at", "valid_until")}


@router.get("/locations", response_model=list[Point])
@warehouse_errors
def locations():
    with connect() as conn:
        return conn.execute("SELECT code, name, latitude::float8, longitude::float8 FROM dim_location ORDER BY name").fetchall()


def latest_rows(location=None):
    with connect() as conn:
        rows = conn.execute("""
            SELECT l.code, l.name, l.latitude::float8, l.longitude::float8,
                   a.id, a.created_at, a.result, a.issued_at + a.horizon_hours * interval '1 hour' AS valid_until,
                   coalesce(a.issued_at <= now() AND a.issued_at + a.horizon_hours * interval '1 hour' > now(), false)
                       AS is_current
            FROM dim_location l
            LEFT JOIN LATERAL (
                SELECT id, result, created_at, issued_at, horizon_hours FROM flood_risk_assessments
                WHERE location_id = l.id AND issued_at <= now() ORDER BY issued_at DESC, id DESC LIMIT 1
            ) a ON true
            WHERE (%s::text IS NULL OR l.code = %s) ORDER BY l.name
        """, (location, location)).fetchall()
    return [{"point": {key: row[key] for key in ("code", "name", "latitude", "longitude")},
             "assessment": stored_result(row) if row["id"] is not None else None,
             "is_current": row["is_current"]} for row in rows]


@router.get("/latest", response_model=list[PointAssessment])
@warehouse_errors
def latest():
    return latest_rows()


@router.get("/{location}/details", response_model=PointAssessment)
@warehouse_errors
def details(location: Location):
    rows = latest_rows(location)
    if not rows:
        raise HTTPException(404, "Unknown monitoring point")
    return rows[0]


def load_config(path):
    return RiskConfig.model_validate_json(Path(path).read_text(encoding="utf-8")) if path else RiskConfig()
