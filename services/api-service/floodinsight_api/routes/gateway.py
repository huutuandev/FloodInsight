from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from ..schemas.gateway import (
    AnalysisQuery, AnalysisScope, BackfillRequest, ClassTrain, ClusterRun, ClusterTrain,
    CoverageQuery, CoverageRow, ETLRequest, Failure, ForecastRow, ForecastTrain, LocationRow, Locations, Meta,
    ModelPage, NextDay, ObservationRow, Page, Period, RainfallRow, Success, Version, WeatherQuery,
)
from ..services.upstream import UpstreamError

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


@router.get("/flood-reports", tags=["flood history"], response_model=Success[list[dict]])
async def flood_reports(request: Request, query: Annotated[Locations, Query()]):
    return await warehouse_page(request, "/warehouse/flood-reports", query, dict, "flood_reports")


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


@router.get("/predictions/outlook", tags=["predictions"], response_model=Success[JsonValue])
async def prediction_outlook(request: Request, location: str = Query(min_length=1, max_length=100)):
    data = await forward(request, "prediction", "/prediction/outlook", query={"location": location})
    return envelope(request, data, "ml_rainfall_outlook")


class OutlookPublication(BaseModel):
    location: str = Field(min_length=1, max_length=100)


@router.get("/predictions/outlook/verification", tags=["predictions"], response_model=Success[JsonValue])
async def prediction_verification(request: Request, location: str = Query(min_length=1, max_length=100)):
    data = await forward(request, "prediction", "/prediction/outlook/verification", query={"location": location})
    return envelope(request, data, "ml_outlook_verification")


@router.post("/predictions/outlook/publish", tags=["predictions"], response_model=Success[JsonValue])
async def publish_outlook(request: Request, payload: OutlookPublication):
    data = await forward(request, "prediction", "/prediction/outlook/publish", body=payload, method="POST")
    return envelope(request, data, "ml_outlook_publication")


@router.get("/predictions/outlook/history", tags=["predictions"], response_model=Success[JsonValue])
async def prediction_outlook_history(request: Request, location: str = Query(min_length=1, max_length=100),
                                     lead_days: int | None = Query(default=None, ge=1, le=7),
                                     start_date: date | None = None, end_date: date | None = None):
    query = {"location": location}
    if lead_days is not None:
        query["lead_days"] = str(lead_days)
    if start_date is not None:
        query["start_date"] = start_date.isoformat()
    if end_date is not None:
        query["end_date"] = end_date.isoformat()
    data = await forward(request, "prediction", "/prediction/outlook/history",
                         query=query)
    return envelope(request, data, "ml_outlook_history")


bind_ml("classifications", "classification", "classification", "ml_rainfall_classification", ClassTrain, NextDay, "predict")


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
async def backfill(request: Request, payload: BackfillRequest):
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

