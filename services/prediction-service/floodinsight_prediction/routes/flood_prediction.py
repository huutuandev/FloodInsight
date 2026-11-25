"""Published supervised flood forecasts. The heuristic index has separate routes."""

from datetime import datetime
import math
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
import numpy as np
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, Field

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.flood_features import TARGET, VERSION
from floodinsight_ml.flood_models import matrix, probabilities
from floodinsight_ml.flood_risk import digest
from floodinsight_ml.flood_store import ERA5, FORECAST, current_features, resolve_issuance
from floodinsight_ml.flood_training_data import FEATURES, TARGET_VERSION, TrainingSpec, input_ready, weather_grids
from floodinsight_ml.schemas import Location, Version
from floodinsight_ml.storage import ModelUnavailable, connect

from ..flood_training import REGISTRY_NAME, SERVABLE, readiness, registry, train

router = APIRouter(prefix="/flood-prediction", tags=["supervised urban flood prediction"])


class PredictRequest(BaseModel):
    location: Location
    issued_at: AwareDatetime | None = None
    version: Version | None = None


class TrainRequest(BaseModel):
    study: TrainingSpec | None = None


class Prediction(BaseModel, extra="allow"):
    location: Location
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    flood_probability: float | None = Field(ge=0, le=1)
    status: str
    risk_classification: str
    model_version: str | None
    model_validation_status: str
    input_quality: dict


@router.get("/readiness")
@warehouse_errors
def flood_readiness():
    return readiness()


@router.post("/train")
@warehouse_errors
def request_training(payload: TrainRequest, request: Request):
    return train(None, request.app.state.settings, study=payload.study)


@router.get("/metrics")
@warehouse_errors
def model_metrics():
    with connect() as conn:
        candidate = conn.execute("""
            SELECT version, training_metadata FROM model_versions WHERE kind = 'flood' AND model_name = %s
            ORDER BY (training_metadata->>'release_status' = 'approved') DESC NULLS LAST, id DESC LIMIT 1
        """, (REGISTRY_NAME,)).fetchone()
    report = readiness()
    if candidate is None:
        return {"status": report["status"], "version": None, "evaluation": None, "readiness": report}
    metadata = candidate["training_metadata"]
    return {"status": metadata.get("release_status", "unavailable"), "version": candidate["version"],
            "evaluation": metadata.get("evaluation"), "feature_version": metadata.get("feature_version"),
            "calibration_method": metadata.get("calibration"), "readiness": report}


@router.get("/results", response_model=list[Prediction])
@warehouse_errors
def prediction_results(location: Annotated[Location | None, Query()] = None, current: bool = False,
                       limit: Annotated[int, Query(ge=1, le=250)] = 100):
    with connect() as conn:
        rows = conn.execute("""
            WITH eligible AS (
                SELECT r.id, l.code, r.issued_at, r.result,
                    row_number() OVER (PARTITION BY l.id ORDER BY r.issued_at DESC, r.id DESC) AS rank
                FROM flood_probability_results r JOIN dim_location l ON l.id = r.location_id
                JOIN model_versions m ON m.id = r.model_version_id
                WHERE (%s::text IS NULL OR l.code = %s)
                  AND (NOT %s OR (r.issued_at <= now() AND now() < r.valid_until))
                  AND m.kind = 'flood' AND m.model_name = %s AND m.training_metadata @> %s
            )
            SELECT id, result FROM eligible WHERE NOT %s OR rank = 1
            ORDER BY issued_at DESC, id DESC LIMIT %s
        """, (location, location, current, REGISTRY_NAME, Jsonb(SERVABLE), current, limit)).fetchall()
    return [row["result"] | {"id": row["id"]} for row in rows]


def score(row, metadata, artifact):
    if not input_ready(row):
        return None, "insufficient_input_data"
    coverage = metadata["validated_locations"].get(row["location"])
    if not coverage:
        return None, "location_not_validated"
    actual_grids = set(weather_grids(row))
    if ({grid[0] for grid in actual_grids} != {ERA5, FORECAST}
            or not actual_grids.issubset(map(tuple, coverage["weather_grids"]))):
        return None, "weather_grid_not_validated"
    if any(not low <= row["features"][name] <= high for name, (low, high) in coverage["feature_range"].items()):
        return None, "inputs_outside_validated_range"
    inputs = matrix([row])
    reference = np.asarray(artifact["reference"], dtype=float)
    probes = np.repeat(inputs, len(FEATURES), axis=0)
    np.fill_diagonal(probes, reference)
    value = float(probabilities(artifact, inputs)[0])
    alternatives = probabilities(artifact, probes)
    if not math.isfinite(value) or not 0 <= value <= 1 or not np.isfinite(alternatives).all():
        return None, "invalid_model_output"
    return {
        "flood_probability": value, "decision_threshold": metadata["threshold"],
        "risk_classification": "elevated" if value >= metadata["threshold"] else "below_alert_threshold",
        "feature_contributions": {
            name: {"value": float(inputs[0, i]), "training_median": float(reference[i]),
                   "probability_change_from_median_probe": value - float(alternatives[i])}
            for i, name in enumerate(FEATURES)
        },
    }, "predicted"


def persist(model_id, location_id, payload):
    result = jsonable_encoder(payload)
    params = (model_id, location_id, payload["issued_at"], payload["valid_until"],
              payload["flood_probability"], digest(result), Jsonb(result))
    with connect() as conn:
        stored = conn.execute("""
            INSERT INTO flood_probability_results
                (model_version_id, location_id, issued_at, valid_until, probability, input_sha256, result)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_version_id, location_id, issued_at, input_sha256) DO NOTHING RETURNING id
        """, params).fetchone()
        if stored is None:
            stored = conn.execute("""
                SELECT id FROM flood_probability_results
                WHERE model_version_id = %s AND location_id = %s AND issued_at = %s AND input_sha256 = %s
            """, (*params[:3], params[5])).fetchone()
    return payload | {"id": stored["id"]}


@router.post("/predict", response_model=Prediction)
@warehouse_errors
def predict(body: PredictRequest, request: Request):
    try:
        issue = resolve_issuance(body.issued_at)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        location = conn.execute("SELECT id, latitude, longitude FROM dim_location WHERE code = %s",
                                (body.location,)).fetchone()
        if location is None:
            raise HTTPException(404, "Unknown monitoring point")
        row = next(item for item in current_features(conn, issue) if item["location"] == body.location)
    response = {
        "location": body.location, "latitude": float(location["latitude"]), "longitude": float(location["longitude"]),
        "issued_at": issue, "valid_from": issue, "valid_until": issue + TARGET,
        "feature_version": VERSION, "target_version": TARGET_VERSION,
        "flood_probability": None, "risk_classification": "unavailable", "model_version": None,
        "model_validation_status": "no_approved_calibrated_model", "feature_contributions": None,
        "input_quality": {"missing_features": [name for name in FEATURES if row["features"][name] is None],
                          "weather_grids": weather_grids(row), "features_complete_at_issue": input_ready(row),
                          "provenance": {name: row["provenance"][name] for name in FEATURES if name in row["provenance"]}},
        "heuristic_assessment_path": "/flood-risk/assessments",
        "limitations": ["24-hour window and 50 m monitoring-point evidence unit",
                        "Provider grid resolution limits neighborhood interpretation",
                        "Median-substitution contributions are local comparisons without causal interpretation"],
    }
    try:
        model, artifact = registry(request.app.state.settings).load(body.version, required_metadata=SERVABLE)
    except ModelUnavailable:
        report = readiness()
        return response | {"status": ("insufficient_training_data" if report["status"] == "insufficient_training_data"
                                      else "no_validated_model"), "readiness": report}
    metadata = model["training_metadata"]
    response |= {"model_version": model["version"], "model_validation_status": "approved_for_supported_conditions",
                 "calibration_method": metadata["calibration"]}
    if (artifact.get("feature_version") != VERSION or artifact.get("target_version") != TARGET_VERSION
            or artifact.get("calibration") != metadata["calibration"]
            or artifact.get("evaluation_sha256") != metadata["evaluation_sha256"]
            or "release_approved_at" not in metadata):
        return response | {"status": "incompatible_model",
                           "model_validation_status": "artifact_metadata_mismatch"}
    if issue < max(model["created_at"], datetime.fromisoformat(metadata["release_approved_at"])):
        return response | {"status": "model_not_available_at_issuance"}
    result, status = score(row, metadata, artifact)
    if result is None:
        return response | {"status": status}
    return persist(model["id"], location["id"], response | result | {"status": status})
