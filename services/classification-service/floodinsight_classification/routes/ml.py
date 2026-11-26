from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import Field

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.daily import FEATURES, DailyTraining, NextDayRequest, inference_input, training_partitions
from floodinsight_ml.daily_results import next_day_results, save_next_day
from floodinsight_ml.schemas import Version
from floodinsight_ml.storage import Models, SOURCE

from ..services.classifier import CLASSES, Thresholds, calibrate_classification, predict_class, train_classifier

router = APIRouter(prefix="/classification", tags=["rainfall intensity classification"])


class TrainingRequest(DailyTraining):
    thresholds: Thresholds = Field(default_factory=Thresholds)


def registry(request):
    return Models("classification", "next-day-rainfall-classifier", request.app.state.settings.artifact_dir)


@router.post("/train")
@warehouse_errors
def train(payload: TrainingRequest, request: Request):
    parts = training_partitions(payload)
    artifact, splits, metrics = train_classifier(parts, payload.thresholds)
    return registry(request).save(artifact, {
        "scope": payload.model_dump(mode="json"), "source": SOURCE, "features": FEATURES,
        "locations": sorted(parts["train"].location.unique().tolist()), "splits": splits,
        "metrics": metrics, "class_order": list(CLASSES), "target": "next local day rainfall intensity",
    })


@router.post("/predict")
@warehouse_errors
def predict(payload: NextDayRequest, request: Request):
    model, artifact = registry(request).load(payload.version)
    target, issued, location, features = inference_input(payload, model)
    raw_label, raw_probabilities = predict_class(artifact, features)
    thresholds = Thresholds(**model["training_metadata"]["scope"].get("thresholds", {}))
    label, probabilities = calibrate_classification(
        payload.location, target, raw_label, raw_probabilities, thresholds,
    )
    return {"version": model["version"], **save_next_day(
        "classification", model["id"], target, issued, location, label, probabilities,
    )}


@router.get("/results")
@warehouse_errors
def results(request: Request, version: Version | None = None,
            limit: Annotated[int, Query(ge=1, le=1000)] = 100,
            offset: Annotated[int, Query(ge=0)] = 0,
            location: str | None = None, start_date: date | None = None,
            end_date: date | None = None):
    model = registry(request).lookup(version)
    return next_day_results("classification", model["id"], limit, offset, location, start_date, end_date)


@router.get("/metrics")
@warehouse_errors
def metrics(request: Request, version: Version | None = None):
    model = registry(request).lookup(version)
    return {"version": model["version"], **model["training_metadata"]}

