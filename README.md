# FloodInsight Da Nang

FloodInsight studies 24-hour urban inundation at monitored points in Da Nang, Vietnam. Rainfall is an input to the flood objective, and the existing rainfall analytics and models remain available. The primary flood prediction API withholds probability until a calibrated candidate passes evidence, evaluation and release gates. The experimental flood risk index has a separate API and can abstain when required inputs are missing.

See [Flood model evaluation](FLOOD_MODEL_EVALUATION.md) for training readiness and the primary prediction endpoints, and [Flood risk index](FLOOD_RISK_INDEX.md) for the heuristic method.

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
| analysis-service | Generate and regenerate time-series patterns from warehouse data with Pandas and NumPy. |
| clustering-service | Cluster complete daily weather periods with K-Means and expose PCA coordinates and evaluation. |
| prediction-service | Manage supervised 24-hour flood prediction, the experimental risk index, and the existing next-day rainfall regressor. |
| classification-service | Train and serve a versioned random forest for next-day rainfall intensity classes. |
| api-service | Route REST requests to all backend services and report dependency health. |
| frontend | Present rainfall analytics and geographic layers with Next.js App Router, Tailwind CSS, Apache ECharts, and React Leaflet. |
| postgres | Persist warehouse data in PostgreSQL 16 on a named volume. |

Planned flow is from weather providers through ingestion into the warehouse. Analytics and ML services consume warehouse data through contracts to be defined. The API exposes results to the dashboard. The ML services have Joblib available for model persistence. The ingestion service captures Open-Meteo modeled weather snapshots. The warehouse backfills ERA5 historical reanalysis. Charts, maps, and analytics data contracts are future work.

Each Python service exposes `GET /health` as a liveness check. The warehouse migration job runs after PostgreSQL can execute an authenticated query. Ingestion and the warehouse API start after migrations succeed. The frontend starts after the public API passes its health check. Services share the project-scoped `floodinsight-internal` bridge network. The warehouse connects to `postgres:5432`, and the frontend forwards `/api/health` to `api-service:8000`. The frontend, public API, ingestion API, warehouse API, analysis API, and the three ML APIs publish ports on the host loopback interface.

## Docker development

Requires Docker with Compose v2. If `.env` is absent, copy `.env.example` to `.env` and fill in `POSTGRES_USER` and `POSTGRES_PASSWORD`. Git ignores `.env`.

~~~sh
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
~~~

With the default ports, the dashboard is at `http://localhost:3000`, the frontend's API health proxy is at `http://localhost:3000/api/health`, and the API is at `http://localhost:8000/health`. The OpenAPI UI is at `http://localhost:8000/docs`. Override `FRONTEND_PORT` and `API_PORT` in `.env`.

Python packages are mounted for live editing and Uvicorn reloads when they change. The default frontend is an optimized Next.js build. Set `FLOODINSIGHT_FRONTEND_TARGET=development` for Fast Refresh with the mounted `frontend/app` directory on Docker Desktop. Rebuild the affected image after changing dependencies or Dockerfiles.

~~~sh
docker compose logs -f api-service frontend
docker compose exec warehouse-service alembic history
docker compose down
~~~

Python services emit JSON records with timestamp, severity, logger, and message. Docker stores all container output with its rotating JSON log driver. Next.js and PostgreSQL retain their native log message format inside those Docker records.

PostgreSQL data persists in the named `postgres-data` volume after `docker compose down`. PostgreSQL applies the user, password, and database settings when initializing an empty data directory. Compose applies warehouse migrations automatically. Apply them explicitly with `docker compose exec warehouse-service alembic upgrade head` when needed. See the [warehouse design and ERD](docs/warehouse-schema.md) for table grains, replay keys, timezone behavior, and verification instructions.


The [Open-Meteo ingestion guide](docs/ingestion.md) documents sampling points, scheduling, timestamp semantics, and the ingestion REST API on `localhost:8001`.

The [historical ETL guide](docs/historical-etl.md) documents checkpointed archive downloads, aggregation, data quality, and the warehouse REST API on `localhost:8002`.

See the [time-series analysis guide](docs/time-series-analysis.md) for pattern generation, ECharts responses, and demo recovery on `localhost:8003`.

See the [machine-learning guide](docs/machine-learning.md) for the three model APIs, artifact lifecycle, and measured evaluation.

See the [REST API gateway guide](docs/api-gateway.md) for routes, filters, response envelopes, and manual operations.

See the [dashboard guide](docs/dashboard.md) for the frontend, data filters, and browser verification.

## Local development and tests

### Recover the running dashboard

Run from the repository root after Compose is healthy. The bootstrap applies remaining migrations,
collects live weather and verified flood sources, fills historical archive gaps, runs the warehouse ETL,
and persists the latest risk assessments. Existing batch and source coverage provide resume checkpoints.
Use the same Compose project and database as the dashboard.

```sh
python scripts/bootstrap_floodinsight.py
```

With Docker Desktop on Windows, add `--docker-host npipe:////./pipe/dockerDesktopLinuxEngine` when that
engine is outside the default CLI context. Override `--api` and `--project` together for a separate stack.
The deployed frontend uses the production runtime. Set `FLOODINSIGHT_FRONTEND_TARGET=development`
before rebuilding the frontend when hot reload is needed.

Recovery leaves flood probabilities unavailable until the evidence gate and model review pass.
See the [runtime verification report](FLOODINSIGHT_RUNTIME_VERIFICATION.md) for the actual run.

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
