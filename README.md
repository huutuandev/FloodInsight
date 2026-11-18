# FloodInsight Da Nang

Rainfall Data Warehouse and Urban Flood Risk Analytics Platform for Da Nang, Vietnam. This Phase 1 scaffold defines service boundaries, local deployment, and health checks.

## Repository layout

```text
.
|-- services/
|   |-- ingestion-service/
|   |-- warehouse-service/
|   |-- analysis-service/
|   |-- clustering-service/
|   |-- prediction-service/
|   |-- classification-service/
|   `-- api-service/
|-- frontend/
|-- docker-compose.yml
|-- config/python-logging.json
|-- .env.example
`-- .gitignore
```

Each Python service has an independently buildable Docker image, runtime and test requirements, and a namespaced Python package with `main.py`, `config.py`, `routes/`, `schemas/`, `services/`, and `repositories/`. Each also has a `tests/` directory.

## Service responsibilities

| Service | Planned responsibilities |
| --- | --- |
| ingestion-service | Fetch and validate Open-Meteo model snapshots and record scheduled and manual runs. |
| warehouse-service | Backfill Open-Meteo ERA5, run historical ETL, expose data quality, and own warehouse migrations. |
| analysis-service | Compute rainfall time series, aggregations, and descriptive statistics with Pandas and NumPy. |
| clustering-service | Group observations or locations using scikit-learn. |
| prediction-service | Train and evaluate rainfall regression models and serve forecasts. |
| classification-service | Train and evaluate models for documented rainfall categories. |
| api-service | Expose dashboard-facing endpoints and call internal services over HTTP. |
| frontend | Present rainfall analytics and geographic layers with Next.js App Router, Tailwind CSS, Apache ECharts, and React Leaflet. |
| postgres | Persist warehouse data in PostgreSQL 16 on a named volume. |

Planned flow is from weather providers through ingestion into the warehouse. Analytics and ML services consume warehouse data through contracts to be defined. The API exposes results to the dashboard. The ML services have Joblib available for model persistence. The ingestion service captures Open-Meteo modeled weather snapshots. The warehouse backfills ERA5 historical reanalysis. Charts, maps, and analytics data contracts are future work.

Each Python service exposes `GET /health` as a liveness check. The warehouse migration job runs after PostgreSQL can execute an authenticated query. Ingestion and the warehouse API start after migrations succeed. The frontend starts after the public API passes its health check. Services share the project-scoped `floodinsight-internal` bridge network. The warehouse connects to `postgres:5432`, and the frontend forwards `/api/health` to `api-service:8000`. The frontend, public API, ingestion API, and warehouse API publish ports on the host loopback interface.

## Docker development

Requires Docker with Compose v2. If `.env` is absent, copy `.env.example` to `.env` and fill in `POSTGRES_USER` and `POSTGRES_PASSWORD`. Git ignores `.env`.

~~~sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
~~~

With the default ports, the dashboard is at `http://localhost:3000`, the frontend's API health proxy is at `http://localhost:3000/api/health`, and the API is at `http://localhost:8000/health`. The OpenAPI UI is at `http://localhost:8000/docs`. Override `FRONTEND_PORT` and `API_PORT` in `.env`.

Python packages and `frontend/app` are mounted from the host for live editing. Uvicorn reloads when Python files change. Next.js uses Fast Refresh with filesystem polling to detect host edits on Docker Desktop. Rebuild the affected image after changing dependencies, Dockerfiles, or frontend configuration outside `frontend/app`.

~~~sh
docker compose logs -f api-service frontend
docker compose exec warehouse-service alembic history
docker compose down
~~~

Python services emit JSON records with timestamp, severity, logger, and message. Docker stores all container output with its rotating JSON log driver. Next.js and PostgreSQL retain their native log message format inside those Docker records.

PostgreSQL data persists in the named `postgres-data` volume after `docker compose down`. PostgreSQL applies the user, password, and database settings when initializing an empty data directory. Compose applies warehouse migrations automatically. Apply them explicitly with `docker compose exec warehouse-service alembic upgrade head` when needed. See the [warehouse design and ERD](docs/warehouse-schema.md) for table grains, replay keys, timezone behavior, and verification instructions.


The [Open-Meteo ingestion guide](docs/ingestion.md) documents sampling points, scheduling, timestamp semantics, and the ingestion REST API on `localhost:8001`.

The [historical ETL guide](docs/historical-etl.md) documents checkpointed archive downloads, aggregation, data quality, and the warehouse REST API on `localhost:8002`.

## Local development and tests

From any Python service directory, create and activate a virtual environment using Python 3.11 or newer, then run:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

For example, from `services/ingestion-service`, run `python -m uvicorn floodinsight_ingestion.main:app --reload`. Phase 1 health tests require no database or provider connection. Each service reads its `FLOODINSIGHT_<SERVICE>_ENVIRONMENT` setting from the process environment.

From `frontend/`, use Node.js 22 or newer:

```sh
npm ci
npm run typecheck
npm run build
```

Use `npm run dev` to run the dashboard locally.

## Future phases

1. Validate provider coverage, licensing, units, and time zone conventions for Da Nang observations.
2. Expand historical source coverage and the quality checks as additional datasets are added.
3. Implement time-series aggregation and evaluate clustering, prediction, and classification with chronological validation where applicable.
4. Define API contracts and connect the dashboard charts and geographic layers to real results.
