from datetime import date, datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
import pandas as pd
from pydantic import BaseModel

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.daily import (
    DAY, FEATURES, DailyTraining, NextDayRequest, daily_rows, inference_input, lag_features, training_partitions,
)
from floodinsight_ml.daily_results import next_day_results, save_next_day
from floodinsight_ml.schemas import Location, Version
from floodinsight_ml.storage import DataUnavailable, Models, SOURCE

from ..services.regression import train_regressor
from ..services.outlook_history import outlook_history, save_outlook, verification_by_lead

router = APIRouter(prefix="/prediction", tags=["rainfall prediction"])


class PredictionTraining(DailyTraining):
    residual_on_climatology: bool = False
    simple_tree: bool = False


class OutlookPublication(BaseModel):
    location: Location
    start_date: date | None = None
    end_date: date | None = None


def registry(request):
    return Models("prediction", "next-day-rainfall-regressor", request.app.state.settings.artifact_dir)


def outlook_registry(request):
    return Models("prediction", "seven-day-rainfall-regressors", request.app.state.settings.artifact_dir)


@router.post("/outlook/train")
@warehouse_errors
def train_outlook(payload: DailyTraining, request: Request):
    rows = daily_rows(payload.start_date - 20 * DAY, payload.end_date, payload.location)
    models, evaluation = {}, {}
    eligible_locations = None
    for lead in range(1, 8):
        parts = training_partitions(payload, lead, rows)
        model, splits, metrics = train_regressor(parts)
        models[lead] = model
        evaluation[str(lead)] = {"splits": splits, "metrics": metrics}
        locations = set(parts["train"].location)
        eligible_locations = locations if eligible_locations is None else eligible_locations & locations
    return outlook_registry(request).save(models, {
        "scope": payload.model_dump(mode="json"), "source": SOURCE, "features": FEATURES,
        "locations": sorted(eligible_locations or []), "evaluation": evaluation,
    })


def build_outlook(location, request, publish=False, start_date=None, end_date=None):
    registry = outlook_registry(request)
    model, artifacts = registry.load(None)
    metadata = model["training_metadata"]
    if metadata["features"] != FEATURES or location not in metadata["locations"]:
        raise DataUnavailable("No trained seven-day rainfall model for this location")
    issued = datetime.now(timezone.utc)
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    today = issued.astimezone(zone).date()
    if (start_date is None) != (end_date is None):
        raise DataUnavailable("Provide both start_date and end_date")
    if start_date is not None and (end_date < start_date or (end_date - start_date).days >= 3660):
        raise DataUnavailable("Select an ordered date range of up to 3,660 days")

    saved = outlook_history(location, today + DAY, today + 7 * DAY,
                            version=model["version"], issue_date=today)
    saved_by_date = {row["target_date"]: row for row in saved}
    wanted_dates = [today + lead * DAY for lead in range(1, 8)
                    if (start_date is None or today + lead * DAY >= start_date)
                    and (end_date is None or today + lead * DAY <= end_date)]
    published = bool(wanted_dates) and all(target in saved_by_date for target in wanted_dates)

    def response(predictions, issue_time):
        return {"version": model["version"], "issued_at": issue_time.isoformat(), "location": location,
                "input_start": (today - 13 * DAY).isoformat(), "input_end": (today - 7 * DAY).isoformat(),
                "availability": metadata["scope"]["availability"], "predictions": predictions,
                "published": published}

    def result(lead, target, mm, issued_at=None):
        metrics = metadata["evaluation"][str(lead)]["metrics"]["test"]
        row = {"lead_days": lead, "target_date": target, "rainfall_mm": mm,
               "test_mae_mm": metrics["xgboost"]["mae_mm"],
               "baseline_mae_mm": metrics["lag_8_persistence"]["mae_mm"]}
        if issued_at is not None:
            row["issued_at"] = issued_at.isoformat()
            row["published"] = True
        return row

    if not wanted_dates:
        return response([], issued)

    if wanted_dates and all(target in saved_by_date for target in wanted_dates):
        if publish:
            return {"published": True, "version": model["version"]}
        predictions = [result(saved_by_date[target]["lead_days"], target,
                              saved_by_date[target]["rainfall_mm"], saved_by_date[target]["issued_at"])
                       for target in wanted_dates]
        return response(predictions, saved_by_date[wanted_dates[0]]["issued_at"])
    rows = daily_rows(today - 13 * DAY, today - 7 * DAY, location)
    days = {row["day"]: row for row in rows}
    generated = {}
    for lead, artifact in sorted(artifacts.items()):
        target = today + lead * DAY
        if target not in wanted_dates or target in saved_by_date:
            continue
        features = lag_features(days, target, issued, "recorded", lead)
        if features is None:
            raise DataUnavailable("Seven complete ERA5 input days must be available at issuance")
        frame = pd.DataFrame([features], columns=FEATURES).astype(float)
        generated[target] = result(lead, target, max(0.0, float(artifact.predict(frame)[0])))
    selected = [generated[target] for target in wanted_dates if target in generated]
    if publish:
        save_outlook(model["id"], rows[-1], issued, today, selected)
        return {"published": bool(selected), "version": model["version"]}

    # Reuse rows already published today and preview only missing dates.
    combined = []
    for target in wanted_dates:
        stored = saved_by_date.get(target)
        if stored:
            combined.append(result(stored["lead_days"], stored["target_date"], stored["rainfall_mm"],
                                   stored["issued_at"]))
        elif target in generated:
            combined.append(generated[target])
    return response(combined, issued)


@router.get("/outlook")
@warehouse_errors
def outlook(location: Location, request: Request, start_date: date | None = None,
            end_date: date | None = None):
    return build_outlook(location, request, start_date=start_date, end_date=end_date)


@router.post("/outlook/publish")
@warehouse_errors
def publish_outlook(payload: OutlookPublication, request: Request):
    return build_outlook(payload.location, request, publish=True,
                         start_date=payload.start_date, end_date=payload.end_date)


@router.get("/outlook/history")
@warehouse_errors
def history(location: Location, lead_days: Annotated[int | None, Query(ge=1, le=7)] = None,
            start_date: date | None = None, end_date: date | None = None):
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None or not 0 <= (end_date - start_date).days < 3660:
            raise DataUnavailable("Select an ordered date range of up to 3,660 days")
        return outlook_history(location, start_date, end_date, lead_days, latest_per_day=lead_days is None)
    return outlook_history(location, today - 7 * DAY, today + 7 * DAY, lead_days)


@router.get("/outlook/verification")
@warehouse_errors
def verification(location: Location):
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    return verification_by_lead(outlook_history(location, today - 90 * DAY, today - DAY))


@router.post("/train")
@warehouse_errors
def train(payload: PredictionTraining, request: Request):
    parts = training_partitions(payload)
    artifact, splits, metrics = train_regressor(
        parts,
        residual_on_climatology=payload.residual_on_climatology,
        simple_tree=payload.simple_tree,
    )
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
    if getattr(artifact, "residual_on_climatology", False):
        monthly = getattr(artifact, "monthly_climatology", {})
        fallback = getattr(artifact, "monthly_climatology_fallback", 0.0)
        value = max(0.0, monthly.get(target.month, fallback) + value)
    return {"version": model["version"], **save_next_day(
        "prediction", model["id"], target, issued, location, max(0.0, value),
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

