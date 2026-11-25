from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime, BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from ..schemas.gateway import (
    AnalysisQuery, AnalysisScope, BatchRequest, ClassTrain, ClusterRun, ClusterTrain,
    CoverageQuery, CoverageRow, ETLRequest, Failure, ForecastRow, ForecastTrain, LocationRow, Locations, Meta,
    ModelPage, NextDay, ObservationRow, Page, Period, RainfallRow, Success, Version, WeatherQuery,
)
from ..services.upstream import UpstreamError
from ..schemas import flood

router = APIRouter(prefix="/api/v1", responses={
    400: {"model": Failure}, 404: {"model": Failure}, 409: {"model": Failure}, 422: {"model": Failure},
    429: {"model": Failure}, 502: {"model": Failure}, 503: {"model": Failure}, 504: {"model": Failure},
})


class HistoryPage(Page):
    limit: int = Field(20, ge=1, le=99)


def envelope(request, data, kind=None, **page):
    return Success(data=data, meta=Meta(request_id=request.state.request_id, kind=kind, **page))


async def forward(request, service, path, *, query=None, body=None, method="GET"):
    return await request.app.state.upstreams.call(
        request.state.request_id, service, path, method=method,
        params=query, body=body.model_dump(mode="json", exclude_none=True) if body is not None else None,
    )


def items(data, service):
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise UpstreamError(502, "bad_gateway", "Service returned an invalid collection", service)
    return data


async def warehouse_page(request, path, query, model, kind):
    raw = await forward(request, "warehouse", path, query=query.model_dump(mode="json", exclude_none=True))
    try:
        if not isinstance(raw, dict) or type(raw.get("has_more")) is not bool:
            raise ValueError
        rows = TypeAdapter(list[model]).validate_python(raw.get("items"))
    except (ValueError, ValidationError) as error:
        raise UpstreamError(502, "bad_gateway", "Warehouse returned an invalid page", "warehouse") from error
    return envelope(request, rows, kind, limit=query.limit, offset=query.offset, has_more=raw["has_more"])


@router.get("/locations", tags=["locations"], response_model=Success[list[LocationRow]])
async def locations(request: Request, query: Annotated[Locations, Query()]):
    return await warehouse_page(request, "/warehouse/locations", query, LocationRow, "locations")


@router.get("/weather", tags=["weather"], response_model=Success[list[ObservationRow]])
@router.get("/weather/observations", tags=["weather"], response_model=Success[list[ObservationRow]])
async def observations(request: Request, query: Annotated[WeatherQuery, Query()]):
    return await warehouse_page(request, "/warehouse/weather/observations", query, ObservationRow, "observed_weather")


@router.get("/weather/forecasts", tags=["weather"], response_model=Success[list[ForecastRow]])
async def forecasts(request: Request, query: Annotated[WeatherQuery, Query()]):
    return await warehouse_page(request, "/warehouse/weather/forecasts", query, ForecastRow, "provider_forecast")


@router.get("/rainfall", tags=["rainfall"], response_model=Success[list[RainfallRow]])
@router.get("/rainfall/daily", tags=["rainfall"], response_model=Success[list[RainfallRow]])
async def daily_rainfall(request: Request, query: Annotated[WeatherQuery, Query()]):
    return await warehouse_page(request, "/warehouse/rainfall/daily", query, RainfallRow, "observed_rainfall_daily")


@router.get("/rainfall/coverage", tags=["rainfall"], response_model=Success[list[CoverageRow]])
async def rainfall_coverage(request: Request, query: Annotated[CoverageQuery, Query()]):
    return await warehouse_page(request, "/warehouse/rainfall/coverage", query, CoverageRow, "rainfall_coverage")


@router.get("/rainfall/{period}", tags=["rainfall"], response_model=Success[list[RainfallRow]])
async def rainfall(request: Request, period: Period, query: Annotated[WeatherQuery, Query()]):
    return await warehouse_page(request, f"/warehouse/rainfall/{period}", query, RainfallRow, f"observed_rainfall_{period}")


@router.get("/analytics", tags=["analytics"], response_model=Success[list[dict]])
async def analytics(request: Request, query: Annotated[AnalysisQuery, Query()]):
    raw = await forward(request, "analytics", "/analysis/patterns", query=query.model_dump(mode="json", exclude_none=True))
    return envelope(request, items(raw, "analytics"), "analytics")


@router.post("/analytics/generate", tags=["analytics"], response_model=Success[list[dict]])
async def generate(request: Request, payload: AnalysisScope):
    raw = await forward(request, "analytics", "/analysis/generate", body=payload, method="POST")
    return envelope(request, items(raw, "analytics"), "analytics")


async def paginated_forward(request, service, path, query, kind):
    params = query.model_dump(mode="json", exclude_none=True) | {"limit": query.limit + 1}
    rows = items(await forward(request, service, path, query=params), service)
    return envelope(request, rows[:query.limit], kind, limit=query.limit, offset=query.offset,
                    has_more=len(rows) > query.limit)


def bind_ml(group, service, upstream_group, kind, train_schema, inference_schema, action):
    async def results(request: Request, query: Annotated[ModelPage, Query()]):
        return await paginated_forward(request, service, f"/{upstream_group}/results", query, kind)

    async def metrics(request: Request, version: Version | None = None):
        query = {"version": version} if version else None
        return envelope(request, await forward(request, service, f"/{upstream_group}/metrics", query=query), kind)

    async def train(request: Request, payload: train_schema):
        return envelope(request, await forward(request, service, f"/{upstream_group}/train", body=payload, method="POST"), kind)

    async def infer(request: Request, payload: inference_schema):
        return envelope(request, await forward(request, service, f"/{upstream_group}/{action}", body=payload, method="POST"), kind)

    for suffix, endpoint, verb, response in (
        ("", results, "GET", Success[list[dict]]),
        ("/results", results, "GET", Success[list[dict]]),
        ("/metrics", metrics, "GET", Success[JsonValue]),
        ("/train", train, "POST", Success[JsonValue]),
        (f"/{action}", infer, "POST", Success[JsonValue]),
    ):
        router.add_api_route(f"/{group}{suffix}", endpoint, methods=[verb], tags=[group],
                             response_model=response, name=f"{group} {suffix.lstrip('/') or 'list'}")


bind_ml("clustering", "clustering", "clustering", "ml_clustering", ClusterTrain, ClusterRun, "run")
bind_ml("predictions", "prediction", "prediction", "ml_rainfall_prediction", ForecastTrain, NextDay, "predict")
bind_ml("classifications", "classification", "classification", "ml_rainfall_classification", ClassTrain, NextDay, "predict")


class FloodRiskRequest(BaseModel):
    location: str = Field(min_length=1, max_length=100)
    issued_at: AwareDatetime | None = None


@router.get("/flood-predictions/readiness", response_model=Success[flood.Readiness])
@router.get("/flood-prediction/readiness", response_model=Success[dict])
async def flood_readiness(request: Request):
    data = await forward(request, "prediction", "/flood-prediction/readiness")
    return envelope(request, data, "supervised_flood_prediction")


@router.post("/flood-predictions/predict", response_model=Success[flood.Prediction])
@router.post("/flood-prediction/predict", response_model=Success[dict])
async def flood_prediction(request: Request, payload: flood.FloodPredictionRequest):
    data = await forward(request, "prediction", "/flood-prediction/predict", body=payload, method="POST")
    return envelope(request, data, "supervised_flood_prediction")


@router.post("/flood-predictions/train", response_model=Success[flood.TrainingResult])
async def train_flood_prediction(request: Request, payload: flood.FloodTrainingRequest):
    data = await forward(request, "prediction", "/flood-prediction/train", body=payload, method="POST")
    return envelope(request, data, "supervised_flood_training")


@router.get("/flood-predictions/results", response_model=Success[list[flood.Prediction]])
async def flood_prediction_results(request: Request, location: str | None = None, current: bool = False,
                                   limit: Annotated[int, Query(ge=1, le=250)] = 100):
    query = {"current": current, "limit": limit}
    if location is not None:
        query["location"] = location
    data = await forward(request, "prediction", "/flood-prediction/results", query=query)
    return envelope(request, items(data, "prediction"), "supervised_flood_prediction")


@router.get("/flood-predictions/metrics", response_model=Success[flood.Metrics])
async def flood_prediction_metrics(request: Request):
    return envelope(request, await forward(request, "prediction", "/flood-prediction/metrics"), "flood_model_metrics")


@router.get("/flood-risk/latest", response_model=Success[list[flood.PointAssessment]])
async def latest_flood_risk(request: Request):
    data = await forward(request, "prediction", "/flood-risk/latest")
    return envelope(request, items(data, "prediction"), "experimental_flood_risk")


@router.get("/flood-risk/locations", response_model=Success[list[LocationRow]])
async def flood_locations(request: Request):
    data = await forward(request, "prediction", "/flood-risk/locations")
    return envelope(request, items(data, "prediction"), "flood_monitoring_points")


@router.get("/flood-risk/history", response_model=Success[list[flood.Assessment]])
async def flood_history(request: Request, location: str | None = None,
                        limit: Annotated[int, Query(ge=1, le=100)] = 20):
    query = {"limit": limit}
    if location is not None:
        query["location"] = location
    data = await forward(request, "prediction", "/flood-risk/history", query=query)
    return envelope(request, items(data, "prediction"), "experimental_flood_risk")


@router.get("/flood-risk/{location}/details", response_model=Success[flood.PointAssessment])
async def flood_details(request: Request, location: str):
    data = await forward(request, "prediction", f"/flood-risk/{quote(location, safe='')}/details")
    return envelope(request, data, "experimental_flood_risk")


@router.post("/flood-risk/generate", response_model=Success[list[flood.Assessment]])
async def generate_flood_risk(request: Request, payload: flood.RiskGeneration):
    data = await forward(request, "prediction", "/flood-risk/generate", body=payload, method="POST")
    return envelope(request, items(data, "prediction"), "experimental_flood_risk")


@router.get("/flood-data/coverage", response_model=Success[flood.Coverage])
async def flood_coverage(request: Request):
    data = await forward(request, "warehouse", "/warehouse/flood-data/coverage")
    return envelope(request, data, "flood_data_coverage")


@router.post("/flood-risk/assessments", response_model=Success[dict])
async def create_flood_assessment(request: Request, payload: FloodRiskRequest):
    data = await forward(request, "prediction", "/flood-risk/assessments", body=payload, method="POST")
    return envelope(request, data, "experimental_flood_risk")


@router.get("/flood-risk/assessments", response_model=Success[list[dict]])
async def flood_assessments(request: Request, location: str | None = None,
                            limit: Annotated[int, Query(ge=1, le=100)] = 20):
    query = {"limit": limit}
    if location is not None:
        query["location"] = location
    data = await forward(request, "prediction", "/flood-risk/assessments", query=query)
    return envelope(request, items(data, "prediction"), "experimental_flood_risk")


@router.get("/clustering/flood-profiles", response_model=Success[dict])
async def flood_profiles(request: Request, issued_at: AwareDatetime | None = None,
                         clusters: Annotated[int, Query(ge=2, le=5)] = 2):
    query = {"clusters": clusters}
    if issued_at is not None:
        query["issued_at"] = issued_at.isoformat()
    data = await forward(request, "clustering", "/clustering/flood-profiles", query=query)
    return envelope(request, data, "exploratory_flood_profiles")


@router.get("/weather/latest", tags=["weather"], response_model=Success[list[dict]])
async def latest(request: Request, location: str | None = None):
    rows = items(await forward(request, "ingestion", "/ingestion/latest"), "ingestion")
    return envelope(request, [row for row in rows if location is None or row.get("location_code") == location],
                    "provider_modeled_current")


@router.post("/weather/ingestion/run", tags=["weather"], response_model=Success[JsonValue])
async def ingest(request: Request):
    return envelope(request, await forward(request, "ingestion", "/ingestion/run", method="POST"), "ingestion_run")


@router.get("/weather/ingestion/status", tags=["weather"], response_model=Success[JsonValue])
async def ingestion_status(request: Request):
    return envelope(request, await forward(request, "ingestion", "/ingestion/status"), "ingestion_status")


@router.get("/weather/ingestion/history", tags=["weather"], response_model=Success[list[dict]])
async def ingestion_history(request: Request, query: Annotated[HistoryPage, Query()]):
    return await paginated_forward(request, "ingestion", "/ingestion/history", query, "ingestion_runs")


@router.post("/weather/backfill", tags=["weather"], response_model=Success[JsonValue])
async def backfill(request: Request, payload: BatchRequest):
    return envelope(request, await forward(request, "warehouse", "/warehouse/backfill", body=payload, method="POST"), "backfill_run")


@router.post("/weather/etl/run", tags=["weather"], response_model=Success[JsonValue])
async def etl(request: Request, payload: ETLRequest):
    return envelope(request, await forward(request, "warehouse", "/warehouse/etl/run", body=payload, method="POST"), "etl_run")


@router.get("/weather/etl/status", tags=["weather"], response_model=Success[JsonValue])
async def etl_status(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return envelope(request, await forward(request, "warehouse", "/warehouse/status", query={"limit": limit}), "warehouse_status")


@router.get("/weather/quality", tags=["weather"], response_model=Success[list[dict]])
async def quality(request: Request, query: Annotated[HistoryPage, Query()]):
    return await paginated_forward(request, "warehouse", "/warehouse/quality", query, "warehouse_quality")


@router.get("/system/status", tags=["system"], response_model=Success[dict])
async def status(request: Request):
    return envelope(request, await request.app.state.upstreams.status(request.state.request_id), "system_status")

