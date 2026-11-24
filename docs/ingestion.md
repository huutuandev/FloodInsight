# Open-Meteo ingestion

The ingestion service polls the Open-Meteo Forecast API for nine fixed representative points. It requests modeled current conditions and a 24-hour hourly series by default. Variables are air temperature, relative humidity, wind speed, total precipitation, rain, showers, sea-level pressure, and WMO weather code. Measurements retain provider units and missing values. Each snapshot records the requested point and the grid coordinates Open-Meteo returned. [Forecast API documentation](https://open-meteo.com/en/docs)

| Location | Latitude | Longitude | Point reference |
| --- | ---: | ---: | --- |
| Hải Châu | 16.076345 | 108.221783 | [Điện Hải Citadel coordinates](https://www.wikidata.org/wiki/Q3917231) |
| Thanh Khê | 16.071259 | 108.191634 | [Thanh Khê coordinate location](https://www.wikidata.org/wiki/Q7710359) |
| Liên Chiểu | 16.072720 | 108.158150 | [Liên Chiểu place coordinates](https://www.geodatos.net/en/coordinates/vietnam/lien-chieu) |
| Cẩm Lệ | 16.015300 | 108.201300 | [Cẩm Lệ locality coordinates](https://mapcarta.com/29658468) |
| Ngũ Hành Sơn | 16.008333 | 108.252500 | [Ngũ Hành Sơn coordinate location](https://www.wikidata.org/wiki/Q7022659) |
| Sơn Trà | 16.101100 | 108.261200 | Representative sampling point |
| Hòa Vang (Hòa Phong) | 15.986700 | 108.140800 | Representative sampling point |
| Hòa Vang (Hòa Bắc) | 16.147200 | 108.016700 | Representative sampling point |
| Hòa Vang (Hòa Khương) | 15.945800 | 108.106900 | Representative sampling point |

These points represent sampling locations. They do not represent administrative centroids, gauge locations, or district-wide averages.

## Additional forecast-model imports

`forecast-refresh` in Docker Compose imports [ECMWF IFS](https://www.ecmwf.int/en/forecasts/datasets/open-data) and [NOAA GFS](https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gfs.php) via Open-Meteo every six hours by default. It loads Hải Châu first for each model. To refresh immediately, run `docker compose exec forecast-refresh python /app/scripts/ingest_multimodel_and_ground_gauges.py --days 7 --past-days 8` after warehouse ETL has seeded the nine sampling points. Inspect `docker compose logs forecast-refresh` and `ingestion_runs` for per-model outcomes. Identical feed, point, valid-time, and content hashes are ignored.

The recent-rainfall table shows the two provider estimates, with today limited to intervals that have ended. It sums hourly total precipitation in millimeters by the interval start in Vietnam time and shows hours available. The seven-day outlook is computed by FloodInsight's own regressors from archived ERA5; see [machine-learning.md](machine-learning.md). Before each scheduled refresh, Compose also asks the warehouse to download and load the newest ERA5 input day required by that outlook.

The [Vietnam National Center for Hydrometeorological Forecasting bulletin for Hải Châu](https://nchmf.gov.vn/kttvsiteE/vi-VN/1/hai-chau-tp-da-nang-w55.html) is available for external reference.

### Nearby rain-gauge reference for Hải Châu

The recent-rainfall table reads station 430018 (Hồ Thạc Gián, Thanh Khê) from the public [Đà Nẵng rain and flood map](https://muangap.danang.gov.vn/). The gauge is approximately 1.9 km from the Hải Châu model sampling coordinates. The frontend server requests timestamped station records and sums the ten-minute depths by Vietnam calendar day, using the start of each interval for the day boundary. The coverage count reports the number of valid intervals returned by the source, out of 144 per day. Missing intervals are not filled. The city's separate rolling 24-hour summary has a different time basis and is not used in the daily table. Station values are retrieved live for comparison and are not loaded into ERA5 or used as training labels.

Open-Meteo's forecast response does not provide a model initialization time for each requested model value. These imports therefore leave `issued_at` NULL, store provider `valid_at` and database `received_at`, and use the content hash to distinguish revisions. They must not be treated as issue-time forecasts in backtests. Additional variables such as precipitation probability and CAPE remain in the raw payload; this importer does not publish them into the canonical weather fact schema.

The repository does not currently contain licensed, source-backed VRAIN observations. The importer intentionally does not create VRAIN rows or derive hourly values from daily totals. Add gauge data only when the actual station identifiers, observation interval, units, source record, and usage rights are available. A daily total cannot be presented as measured hourly rainfall.

## Timing, storage, and recovery

- The service saves modeled current conditions and stitched hourly values in `raw_weather_forecasts`. Open-Meteo derives current conditions from weather models, and the Forecast API does not give a model initialization timestamp for each value. `valid_at` holds the provider’s timestamp, `received_at` holds response receipt time, and `issued_at` remains NULL for this feed. Accumulated precipitation retains Open-Meteo’s interval-ending convention and is stored with the interval length. The existing observation and fact tables remain available for later processing. [Forecast API documentation](https://open-meteo.com/en/docs) · [Open-Meteo model updates](https://open-meteo.com/en/docs/model-updates)
- An additive migration extends the existing raw forecast and run tables. It keeps the issue-time key for providers that report issuance. This collector deduplicates by feed, sample point, valid time, and a SHA-256 digest of the validated snapshot. Identical content retains its first receipt time, including when it reappears after a revision. A successful poll may insert zero records. The batch and successful run status commit together.
- APScheduler attempts a poll every five minutes by default, with coalescing and a one-instance limit. A PostgreSQL advisory lock also prevents overlaps with manual requests and other workers. The interval governs polling. Provider data can update on a different cadence. [APScheduler configuration](https://apscheduler.readthedocs.io/en/3.x/userguide.html) · [Open-Meteo model updates](https://open-meteo.com/en/docs/model-updates)
- Network failures and retryable HTTP responses use bounded retries, with a default of three attempts and a 12-second request deadline. A poll validates all nine locations before writing any snapshots. Run history records failed polls and a short error reason. The next worker that acquires the lock marks an interrupted run as failed before starting a new run.

## Local API

`docker compose up -d --build` runs the warehouse migration job before ingestion starts. The development API binds to `127.0.0.1:8001` by default. If running outside Compose, apply the warehouse Alembic migrations first and supply the PostgreSQL connection environment variables. Scheduler and provider settings are listed in `.env.example`.

| Request | Result |
| --- | --- |
| `POST /ingestion/run` | Runs one batch synchronously. Returns the completed run, HTTP 409 if another poll has the lock, or HTTP 502 with the saved run detail for a provider failure. |
| `GET /ingestion/status` | Scheduler settings, next scheduled execution for this process, and the latest persisted run. |
| `GET /ingestion/latest` | Most recent stored modeled-current snapshot for each sampled location, sorted by location code. |
| `GET /ingestion/history?limit=20&offset=0` | Runs newest first, including start and finish times, trigger, outcome, inserted count, and error if any. |

## Testing

Install `requirements-dev.txt` from `services/ingestion-service` and run `python -m pytest`. Provider tests replay a live Hải Châu response captured on 2026-11-18. Enable PostgreSQL tests with `FLOODINSIGHT_RUN_INGESTION_DB_TESTS=1` and point the connection settings at a migrated, disposable database named `floodinsight_ingestion_test`. Those tests write isolated feed records to verify persistence, deduplication, scheduling, overlap protection, and recovery.
