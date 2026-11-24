# Historical weather backfill and ETL

The warehouse downloads Open-Meteo ERA5 reanalysis for the nine [Da Nang sampling points](ingestion.md). ERA5 is the fixed source throughout the date range. It provides gridded estimates for liquid rain, total precipitation, temperature, humidity, and wind. The two coordinates recorded for each sample distinguish the requested point and the provider’s grid cell. [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)

## Run the pipeline

Start the warehouse with `docker compose up -d --build warehouse-service`. Compose applies migrations first. The local REST API defaults to `http://127.0.0.1:8002`; its OpenAPI interface is at `/docs`. Configure the port, provider URL, request timeout, and retry attempts in `.env` using `.env.example`.

| Endpoint | Behavior |
| --- | --- |
| `POST /warehouse/backfill` | Downloads pending point/month batches for an inclusive local date range. Commits raw rows and checkpoints together. |
| `POST /warehouse/etl/run` | Transforms downloaded checkpoints within the requested range and replaces their hourly and daily facts atomically. |
| `GET /warehouse/status?limit=20` | Returns recent executions, their outcomes and progress, and total downloaded/loaded checkpoint counts. |
| `GET /warehouse/quality?limit=20&offset=0` | Returns paginated quality reports for loaded checkpoints, newest first. |

Send `start_date`, `end_date`, and optionally `max_batches`. Both POST requests are synchronous, so use small batches when running behind a request timeout. The defaults are five downloads and 20 ETL batches per invocation. Repeat the same multi-year range until `progress.remaining_batches` is zero for each operation. A successful invocation means its bounded work completed. A failed invocation returns its saved run record with an error reason. Re-submit the range after correcting the error to resume from saved checkpoints. An advisory lock prevents concurrent warehouse operations.

```sh
curl -X POST http://127.0.0.1:8002/warehouse/backfill \
  -H 'Content-Type: application/json' \
  -d '{"start_date":"2023-10-01","end_date":"2023-10-31","max_batches":5}'
curl -X POST http://127.0.0.1:8002/warehouse/etl/run \
  -H 'Content-Type: application/json' \
  -d '{"start_date":"2023-10-01","end_date":"2023-10-31"}'
```

The oldest complete local date is 1940-01-02. The API restricts requests to dates at least five days behind UTC today to account for the documented ERA5 publication lag. Availability can vary. All-missing batches fail without writing a checkpoint. Checkpoints identify the source, point, and actual date bounds, so overlapping requests can reuse raw records even if their checkpoint boundaries differ. ETL selects only checkpoints fully contained in the requested range. Use the original backfill range to process all its checkpoints. To rebuild completed batches, set `reprocess: true` and pass the previous response’s `progress.last_batch_id` as `after_batch_id` on subsequent invocations.

## Storage and data quality

- The raw layer retains ERA5 values, model, units, grid metadata, provider timestamps, and retrieval timestamps in `raw_weather_observations` under a dedicated source code. An identical source, point, and valid instant is retained once, with its first receipt and payload. ERA5 is reanalysis, so its source identity remains separate from live forecast snapshots and any future station measurements.
- ETL validates units on extraction and builds UTC hourly facts. Liquid rain ending at hour `t + 1h` is assigned to the interval starting at `t`. Temperature, humidity, and wind use measurements labeled at `t`. The batch includes the end-boundary raw hour so the final interval can be computed.
- Missing or invalid measurements stay NULL. An hour with no usable measurement produces no hourly fact. A real zero rainfall reading contributes to coverage. Each checkpoint reports expected and loaded hours, omitted hours, missing timestamps, missing and invalid values per measure, and hours with valid rain.
- Hourly facts use the existing time, source, and location dimensions. Daily rainfall facts sum non-NULL hourly rain by Vietnam local date. The `vw_weather_daily`, `vw_weather_weekly`, and `vw_weather_monthly` views add rainfall totals, observed and expected hours, and hourly-weighted averages of temperature, humidity, and wind. Weeks start Monday. Periods with some observations can be partial. Rainfall stays NULL in the views when no rain measurements contribute.
- Migration `0003` creates `warehouse_runs`, `historical_batches`, and the aggregate views. It reuses existing fact and dimension tables. Calendar coverage allows longer days during historical Vietnam timezone transitions.

## Leakage controls

`read_rainfall` and `chronological_rainfall_splits` in `floodinsight_warehouse.services.ml_dataset` prepare chronological rainfall splits. Inputs are exact hourly lags for the same location and source. A lag must have been received by the prediction issue time. Missing labels and incomplete lag windows are dropped. Training labels must end and have become available by the cutoff. Test issue times must be at or after the cutoff. The boundary excludes training examples whose label horizon crosses the split.

A modern ERA5 backfill can provide historical labels, coverage, and descriptive analytics. Recorded receipt dates generally make it ineligible as a feature source for forecasts issued at historical times. The helper returns empty splits when there is no evidence that the features were available at issuance. Any future preprocessing must be fitted on the training split.

## Tests

Run `python -m pytest` from `services/warehouse-service` after installing the development requirements. Set `FLOODINSIGHT_RUN_WAREHOUSE_DB_TESTS=1` with an isolated, migrated PostgreSQL database named `floodinsight_warehouse_test` to run database tests. The historical fixture is a real ERA5 response for Hải Châu covering 2023-10-13 local time, with adjacent UTC hours for interval alignment.

