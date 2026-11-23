from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import Field

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.schemas import RunWindow, Version, Window
from floodinsight_ml.storage import Models, SOURCE

from ..repositories.clusters import daily_features, results, save_assignments
from ..services.clusters import apply_clusters, train_clusters

router = APIRouter(prefix="/clustering", tags=["clustering"])


class TrainRequest(Window):
    clusters: Annotated[int, Field(ge=2, le=12)] = 3
    scan_k: bool = False


def registry(request):
    return Models("clustering", "daily-weather-kmeans", request.app.state.settings.artifact_dir)


@router.post("/train")
@warehouse_errors
def train(payload: TrainRequest, request: Request):
    artifact, metrics = train_clusters(daily_features(payload), payload.clusters, payload.scan_k)
    return registry(request).save(artifact, {
        "scope": payload.model_dump(mode="json"), "source": SOURCE, "metrics": metrics,
    })


@router.post("/run")
@warehouse_errors
def run(payload: RunWindow, request: Request):
    model, artifact = registry(request).load(payload.version)
    rows = daily_features(payload)
    assignments = apply_clusters(rows, artifact)
    save_assignments(model["id"], rows, assignments)
    groups = {}
    for row, (label, details) in zip(rows, assignments):
        groups.setdefault(label, []).append([details["pc1"], details["pc2"], row["location"]])
    return {
        "version": model["version"], "stored_rows": len(rows),
        "option": {"xAxis": {"name": "PC1"}, "yAxis": {"name": "PC2"}, "legend": {},
                   "tooltip": {}, "series": [
                       {"type": "scatter", "name": f"Cluster {label}", "data": points}
                       for label, points in sorted(groups.items())
                   ]},
    }


@router.get("/results")
@warehouse_errors
def get_results(request: Request, version: Version | None = None,
                limit: Annotated[int, Query(ge=1, le=1000)] = 100,
                offset: Annotated[int, Query(ge=0)] = 0,
            location: str | None = None, start_date: date | None = None,
            end_date: date | None = None):
    model = registry(request).lookup(version)
    return results(model["id"], limit, offset, location, start_date, end_date)


@router.get("/metrics")
@warehouse_errors
def metrics(request: Request, version: Version | None = None):
    model = registry(request).lookup(version)
    return {"version": model["version"], **model["training_metadata"]}

