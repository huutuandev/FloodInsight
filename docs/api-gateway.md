# FloodInsight REST API gateway

Start the Compose stack with `docker compose up -d --build`. Swagger UI is at `http://127.0.0.1:8000/docs`, and the OpenAPI document is at `/openapi.json`. Upstream URLs use Docker DNS by default. The six URLs, timeouts, and comma-separated Next.js CORS origins can be overridden with the `FLOODINSIGHT_API_*` settings in Compose.

## Resources

| Group | Read endpoints | Manual operations |
| --- | --- | --- |
| Locations | `GET /api/v1/locations` lists warehouse locations | |
| Weather | `GET /api/v1/weather` or `/weather/observations`, `/weather/forecasts`, `/weather/latest`, `/weather/ingestion/status`, `/weather/ingestion/history`, `/weather/etl/status`, `/weather/quality` | `POST /api/v1/weather/ingestion/run`, `/weather/backfill`, `/weather/etl/run` |
| Rainfall | `GET /api/v1/rainfall` (daily) and `/rainfall/{daily,weekly,monthly}` | |
| Analytics | `GET /api/v1/analytics` | `POST /api/v1/analytics/generate` |
| Clustering | `GET /api/v1/clustering` or `/clustering/results`, `/clustering/metrics` | `POST /api/v1/clustering/train`, `/clustering/run` |
| Predictions | `GET /api/v1/predictions` or `/predictions/results`, `/predictions/metrics` | `POST /api/v1/predictions/train`, `/predictions/predict` |
| Classifications | `GET /api/v1/classifications` or `/classifications/results`, `/classifications/metrics` | `POST /api/v1/classifications/train`, `/classifications/predict` |
| System | `GET /api/v1/system/status` | |

Relative route fragments in this table use the `/api/v1` prefix. Location filters use warehouse codes such as `hai-chau`. Observations, forecasts, rainfall, and analytics require an inclusive Vietnam-local `start_date` and `end_date`. Where documented in Swagger, use `source`, `version`, or `pattern` for a narrower selection. ML result lists accept optional dates and location. Collections with variable row count support `limit` and `offset`; `meta.has_more` indicates a subsequent page. Warehouse locations become available after data is loaded into the dimension.

The weather fact read includes reanalysis where the source is ERA5. Provider forecasts expose the latest stored revision per source, location, and valid time, including provider issue time when known and receipt time. The modeled-current endpoint reads the ingestion service. ML predictions and classifications use independent result collections. The `meta.kind` and source fields identify what each response represents. Rainfall date filters select stored calendar periods that intersect the dates. Weekly or monthly totals are returned at their full stored period grain, with coverage.

## Contracts and operations

A successful API response has `data` and `meta`. A valid empty collection returns HTTP 200 and `data: []`. Errors have `error.code`, `error.message`, and optional upstream service and validation details, plus `meta.request_id`. The request ID appears in the response header and gateway JSON logs. Gateway errors retain actionable upstream 4xx statuses, use 502 for invalid upstream responses, 503 for unavailable services or a database connection failure, and 504 for timeouts.

`GET /health` is the gateway process liveness check. `GET /ready` checks all dependencies and returns HTTP 503 when degraded. `GET /api/v1/system/status` provides a monitoring report even during outages. It checks the six service liveness endpoints in parallel and runs a PostgreSQL query through warehouse readiness. The report names each failing dependency.

Manual operations forward to their owning services. Regenerate analytics with its original location, source, and dates. Use the original version and input scope to regenerate clusters or reissue ML predictions. An ETL/backfill operation can report a recorded failed run in its result, so inspect `data.status`. The gateway does not retry POST operations automatically. After a timeout, consult the owning service's status or results before reissuing the request. See the [historical ETL guide](historical-etl.md), [analysis guide](time-series-analysis.md), and [machine-learning guide](machine-learning.md).

Compose binds the gateway to loopback. CORS permits the configured browser origins. Keep manual processing endpoints in a trusted environment or place authentication and authorization in front of them before external deployment.

