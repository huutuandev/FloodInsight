from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.daily import FEATURES, DailyTraining, NextDayRequest, inference_input, training_partitions
from floodinsight_ml.daily_results import next_day_results, save_next_day
from floodinsight_ml.schemas import Version
from floodinsight_ml.storage import Models, SOURCE

from ..services.regression import train_regressor

router = APIRouter(prefix="/prediction", tags=["rainfall prediction"])


def registry(request):
    return Models("prediction", "next-day-rainfall-regressor", request.app.state.settings.artifact_dir)


@router.post("/train")
@warehouse_errors
def train(payload: DailyTraining, request: Request):
    parts = training_partitions(payload)
    artifact, splits, metrics = train_regressor(parts)
    return registry(request).save(artifact, {
        "scope": payload.model_dump(mode="json"), "source": SOURCE, "features": FEATURES,
        "locations": sorted(parts["train"].location.unique().tolist()),
        "splits": splits, "metrics": metrics, "target": "next local day rainfall total in mm",
    })


@router.post("/predict")
@warehouse_errors
def predict(payload: NextDayRequest, request: Request):
    model, artifact = registry(request).load(payload.version)
    target, issued, location, features = inference_input(payload, model)
    value = float(artifact.predict(features)[0])
    return {"version": model["version"], **save_next_day(
        "prediction", model["id"], target, issued, location, value,
    )}


@router.get("/results")
@warehouse_errors
def results(request: Request, version: Version | None = None,
            limit: Annotated[int, Query(ge=1, le=1000)] = 100,
            offset: Annotated[int, Query(ge=0)] = 0,
            location: str | None = None, start_date: date | None = None,
            end_date: date | None = None):
    model = registry(request).lookup(version)
    return next_day_results("prediction", model["id"], limit, offset, location, start_date, end_date)


@router.get("/metrics")
@warehouse_errors
def metrics(request: Request, version: Version | None = None):
    model = registry(request).lookup(version)
    return {"version": model["version"], **model["training_metadata"]}

