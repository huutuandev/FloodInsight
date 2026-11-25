# FloodInsight runtime recovery

Verified 25 November 2026, Vietnam time, against the running default `floodinsight` project. Dashboard at [localhost:3000](http://localhost:3000) and API documentation at [localhost:8000/docs](http://localhost:8000/docs). The default stack remains running.

## Root causes and repairs

1. The live stack used `floodinsight_postgres-data`. Phase 1 and QA had separate named volumes. The live volume was at migration `0008` and held 125 current or hourly weather snapshots, but zero warehouse locations, rainfall facts, or flood evidence. Open-Meteo ingestion writes the raw feed without registering warehouse locations. Migration `0009` now registers the five canonical points independently of imports and training, leaving existing records intact.
2. The default project's historical backfill, ETL, flood imports, assessment generation, and legacy output generation had never run. The recovery executed those workflows. The dashboard's existing coverage-driven dates now select when data actually exists. The rainfall panel distinguishes uncollected history from an empty selected date range, and Flood Overview shows provider-modeled current conditions and available forecast accumulations.
3. The weather feed requested 24 hourly timestamps starting in the current hour. This is too short for a complete 24-hour feature at the next whole-hour decision. Raw snapshot deduplication also discarded the membership of repeated values in later forecast runs. The default request now asks for 26 hours. Migration `0010` retains each actual hourly receipt separately from its deduplicated values. Feature construction uses the receipt and run boundaries to avoid mixing forecasts or using receipts that arrived after issuance. Older missing memberships cannot be reconstructed from launch history.
4. Next.js dev logs showed React hydration warnings. The changed attributes were `fdprocessedid`, `data-gr-ext-installed`, and `monica-*`, from browser-side injection. Compose now serves the already-supported optimized Next.js runtime by default, with an opt-in Fast Refresh target. Clean Chrome verification checks console hydration messages and page errors. Browser extensions can still modify a personal browser's DOM.

The older Phase 1 and QA volumes remain intact. Recovery retained the active volume and did not replace any model volume. It reused a verified 14:53 UTC Open-Meteo run from the retained QA replica. Ten active flood assets matched the prior source references and SHA-256 digests, so recovery restored their earlier recorded receipts and retained the newer receipt in metadata. The import reused existing raw snapshot keys, inserted ten missing snapshots, and linked the 120 original hourly receipts. No missing provider issuance timestamp was assigned.

## Active PostgreSQL counts

| Table | Before | After |
| --- | ---: | ---: |
| `alembic_version` | 1 at `0008` | 1 at `0010` |
| `dim_location` | 0 | 5 |
| `dim_date` | 0 | 307 |
| `dim_time` | 0 | 7,345 |
| `data_sources` | 1 | 7 |
| `dim_weather_source` | 0 | 1 |
| `raw_weather_observations` | 0 | 36,735 |
| `raw_weather_forecasts` | 125 | 150 |
| `forecast_snapshot_receipts` | Table absent | 760 |
| `fact_weather_hourly` | 0 | 36,720 |
| `fact_rainfall_daily` | 0 | 1,530 |
| `fact_weather_forecast_hourly` | 0 | 0 |
| `historical_batches` | 0 | 60 |
| `ingestion_runs` | 1 | 26 |
| `warehouse_runs` | 0 | 40 |
| `analysis_results` | 0 | 120 |
| `model_versions` | 0 | 3 legacy, 0 flood |
| `clustering_results` | 0 | 1,520 legacy |
| `prediction_results` | 0 | 5 legacy |
| `classification_results` | 0 | 5 legacy |
| `flood_dataset_assets` | 0 | 15 |
| `flood_events` | 0 | 1 |
| `flood_observations` | 0 | 0 |
| `flood_terrain_features` | 0 | 25 |
| `flood_hydrology_observations` | 0 | 264 |
| `flood_risk_assessments` | 0 | 10, comprising five initial and five with restored evidence |
| `flood_probability_results` | 0 | 0 |

Counts are from the verified post-recovery snapshot. Live scheduled collection can advance the counts. The historical ETL populated observed hourly and daily facts. Forecast features follow the raw snapshot-and-receipt path, so the separate legacy hourly forecast fact table stayed empty. The hourly observation facts had zero duplicate point/source/hour keys and zero null rainfall values.

## Real sources collected and availability

| Source | Collected and persisted |
| --- | --- |
| Open-Meteo current and hourly forecast | Five current snapshots already existed. The final snapshot inventory had 135 unique hourly and 15 current rows, including the retained run. Two consecutive live refreshes inserted zero new raw rows and each recorded 26 hourly receipts at each point. The receipt SQL confirmed each run contained 24 future hourly endpoints for the next whole-hour decision. |
| Open-Meteo ERA5 archive | 36,735 raw samples across the five points and 36,720 curated hours. Coverage is 14–15 October 2022, 1 June 2023–29 February 2024, and 21 October–19 November 2026, in Vietnam local dates. That is 306 days per point with gaps between windows. All five points share rainfall grid 16.00° N, 108.25° E. |
| Copernicus DEM | Five GLO-90 elevation, five GLO-30 elevation and five GLO-30 slope results. All expected samples persisted. |
| ESA WorldCover | Five centre classes and five built-up fractions from the verified 2021 tile. |
| ERA5 modeled soil wetness | 120 hourly samples on each of 13 October 2023 and 18 November 2026 UTC across five points sharing one cell. |
| Open-Meteo Marine | 24 hourly modeled offshore sea-level values at the returned grid near 16.208336° N, 108.29167° E. Local river stage, discharge and tide-gauge observations were unavailable. |
| Vietnam Government Portal | One indexed regional October 2022 flood event. Zero verified observations within the study-point targets and zero monitored dry labels. [Source inventory](FLOOD_DATA_SOURCES.md) |

Hải Châu returned 73.6 mm for 13 October 2023 and 179.5 mm and 37.0 mm for 14 and 15 October 2022 respectively, all over 24 loaded hours. These are ERA5 grid values. They support historical charting without treating the five copies as independent weather observations.

## Live API, features and risk

The gateway returned `status: ok` for all eight component checks, including PostgreSQL. Both location endpoints returned identical point codes and coordinates. Gateway and Next proxy responses agreed for flood location details, data coverage, readiness, assessment replay, and rainfall pages. Examples from the live stack follow.

| Request | Observed response |
| --- | --- |
| `GET /api/v1/weather/latest` | Hải Châu at 15:00 UTC returned 23.1 °C, 94% humidity, and 1.9 mm modeled precipitation over 15 minutes, received at 15:05:59 UTC. |
| `GET /api/v1/rainfall/daily?location=hai-chau&start_date=2023-10-13&end_date=2023-10-13` | `rainfall_total_mm: 73.6`, `rainfall_hours: 24`, `expected_hours: 24`. |
| `GET /api/v1/flood-risk/hai-chau/details` | 33.8 mm forecast for six hours, 42.8 mm for 12 hours, and null for 24 hours. The method is `flood-risk-v1`, validation `experimental_heuristic_unvalidated`. |
| `POST /api/v1/flood-predictions/train` and `POST /api/v1/flood-predictions/predict` | `insufficient_training_data`. The predict route returned null probability. |
| `GET /api/v1/flood-predictions/metrics` and `GET /api/v1/flood-predictions/results` | Null evaluation and an empty validated results list. |
| `GET /api/v1/clustering/flood-profiles` | Five complete point profiles in two exploratory groups of four and one. These are terrain profiles. |

The `flood-point-v1` feature export for 25 November 2026 15:00 UTC (22:00 ICT) returned five rows. Each had receipt-safe 6 h and 12 h forecast rain, elevation, slope, land cover, built-up fraction, and offshore sea level. The older forecast run lacked the final two endpoints of the required 24-hour horizon. The complete new forecast runs and the recent soil refresh arrived after the decision. Near-real-time measured rainfall for the preceding day was also absent. No late values were credited to this decision. The export hash is `88094eb132c8eabeb491f97aad6de0e7fd88def1624f9bac444d9d82b5d24281`.

| Point | Persisted assessment ID | Category | Score and probability |
| --- | ---: | --- | --- |
| Cẩm Lệ | 33 | Insufficient Data | Both null |
| Hải Châu | 34 | Insufficient Data | Both null |
| Liên Chiểu | 35 | Insufficient Data | Both null |
| Ngũ Hành Sơn | 36 | Insufficient Data | Both null |
| Thanh Khê | 37 | Insufficient Data | Both null |

All five were valid through 26 November 2026 15:00 UTC, with 0.15 nominal factor-weight coverage. Each returned the missing 24-hour forecast, recent 24-hour observation, recent hourly maximum, and delayed soil feature, along with input timestamps and source references. Identical requests reused the saved assessments.

## Models

There were zero confirmed wet and dry targets, zero independently linked point events, and five unknown decisions in the live export because the outcome horizon was open. There was one regional flood-event record. No flood model was fitted, calibrated, registered, or published. The frontend displays the blocked evidence gate.

The existing legacy recovery trained and registered three separate weather models from the real archive. The stored outputs included 1,520 weather cluster rows, five next-day rainfall totals and five rainfall class results. On the legacy retrospective rainfall test, the random forest achieved MAE 12.40 mm and RMSE 13.37 mm, while lag-8 persistence achieved MAE 6.76 mm and RMSE 12.35 mm. The rainfall classifier's test macro F1 was 0.1905 on 260 point-days and classified every test row as Light Rain. These shared-grid legacy results do not evaluate flood forecasting.

## Verification and changed files

The run executed `docker compose config --quiet`, `ps -a`, `logs --tail=200`, and `up -d --build --wait`. Nine runtime containers were healthy and the migration job exited with code 0. PostgreSQL checks enumerated actual tables and counted forecast members by run and point. Backfill, ETL, collector, feature export, assessment and readiness commands ran on the active project. A second bootstrap run completed all three archive windows with zero new downloads or fact rows and skipped both existing raster samples.

Ingestion tests passed 7/7 against a disposable migrated database, including unchanged raw values in two distinct forecast runs. On that database, migration `0010` exposed five seeded locations with zero weather facts. The flood source, feature and risk suite had 21 passes and two opt-in integration skips. Live gateway and browser checks covered assessment persistence and exploratory terrain grouping separately. The legacy registry assertion passed 1/1, and classification passed 3/3 against its separate QA database. Frontend type checking, lint, the optimized Next.js Docker build and live gateway/proxy contracts passed. The clean Chrome test covered all six dashboard sections, five selector entries and map markers, archive-backed default dates, live weather, rainfall chart rendering, assessment evidence, real legacy model charts, readiness and coverage, mobile layout, theme switching and a simulated API outage. Its page-error and hydration assertions passed.

Changed files in this recovery:

- `docker-compose.yml` and `.env.example` for the frontend deployment target and forecast horizon.
- `services/warehouse-service/migrations/versions/0009_seed_monitoring_points.py`, `0010_forecast_receipts.py`, and `services/warehouse-service/migrations/env.py` for warehouse initialization and forecast receipts.
- `services/ingestion-service/floodinsight_ingestion/config.py`, `repositories/ingestion.py`, and `services/ml-common/floodinsight_ml/flood_store.py` for weather collection and receipt-aware features.
- `services/warehouse-service/floodinsight_warehouse/flood_data.py`, `scripts/bootstrap_floodinsight.py` and `README.md` for replay checkpoints and startup.
- `frontend/app/dashboard/dashboard.tsx`, `flood-panels.tsx`, `weather-panels.tsx`, and `frontend/tests/dashboard.mjs` for populated views, empty states and browser assertions.
- `services/ingestion-service/tests/test_ingestion_db.py`, `services/clustering-service/tests/test_registry_integrity.py` and `services/classification-service/tests/test_classification.py` for forecast receipt coverage and the previously failing legacy assertions. The registry mock now reads the version parameter, and the classification replay uses numerical tolerance for probabilities while keeping other fields exact.

## Startup and recovery

Use the same Compose project and PostgreSQL credentials configured in `.env`. The default uses the existing `floodinsight` volumes. For a 24-hour decision horizon, set `FLOODINSIGHT_INGESTION_FORECAST_HOURS=26` if an older `.env` overrides the new default. From the repository root with host Python 3.11 or later:

```powershell
$engine = 'npipe:////./pipe/dockerDesktopLinuxEngine'
docker -H $engine compose config --quiet
docker -H $engine compose up -d --build --wait
python scripts/bootstrap_floodinsight.py --docker-host $engine
```

Omit the engine arguments when Docker already selects the correct engine. The bootstrap uses persisted completion checkpoints and bounded retries. Use `--start` and `--end` to select the longer archive window, `--refresh-weather` to request a current collection, and `--study` only for an explicit reviewed flood study. A second run after the next whole hour can use newly received features. The normal training and publication gates still apply. To recover legacy weather outputs separately, this run used:

```powershell
docker -H $engine compose run -T --rm --no-deps -v "${PWD}/scripts:/recovery:ro" warehouse-service python /recovery/recover_dashboard.py --api http://api-service:8000 --phase outputs --start 2023-06-01 --end 2024-02-29
```

The remaining scientific blockers are independently verified inundation and dry surveillance at the monitoring points, a sufficient cohort of independent events and grids, and recent point-relevant rainfall observations available at decision time. No meaningful flood probability, calibration curve, or flood prediction accuracy can be reported from the current evidence.
