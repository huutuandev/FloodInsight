# Open-Meteo ingestion

The ingestion service polls the Open-Meteo Forecast API for five fixed representative points. It requests modeled current conditions and a 24-hour hourly series by default. Variables are air temperature, relative humidity, wind speed, total precipitation, rain, showers, sea-level pressure, and WMO weather code. Measurements retain provider units and missing values. Each snapshot records the requested point and the grid coordinates Open-Meteo returned. [Forecast API documentation](https://open-meteo.com/en/docs)

| Location | Latitude | Longitude | Point reference |
| --- | ---: | ---: | --- |
| Hải Châu | 16.076345 | 108.221783 | [Điện Hải Citadel coordinates](https://www.wikidata.org/wiki/Q3917231) |
| Thanh Khê | 16.071259 | 108.191634 | [Thanh Khê coordinate location](https://www.wikidata.org/wiki/Q7710359) |
| Liên Chiểu | 16.072720 | 108.158150 | [Liên Chiểu place coordinates](https://www.geodatos.net/en/coordinates/vietnam/lien-chieu) |
| Cẩm Lệ | 16.015300 | 108.201300 | [Cẩm Lệ locality coordinates](https://mapcarta.com/29658468) |
| Ngũ Hành Sơn | 16.008333 | 108.252500 | [Ngũ Hành Sơn coordinate location](https://www.wikidata.org/wiki/Q7022659) |

These points represent sampling locations. They do not represent administrative centroids, gauge locations, or district-wide averages.

## Timing, storage, and recovery

- The service saves modeled current conditions and stitched hourly values in `raw_weather_forecasts`. Open-Meteo derives current conditions from weather models, and the Forecast API does not give a model initialization timestamp for each value. `valid_at` holds the provider’s timestamp, `received_at` holds response receipt time, and `issued_at` remains NULL for this feed. Accumulated precipitation retains Open-Meteo’s interval-ending convention and is stored with the interval length. The existing observation and fact tables remain available for later processing. [Forecast API documentation](https://open-meteo.com/en/docs) · [Open-Meteo model updates](https://open-meteo.com/en/docs/model-updates)
- An additive migration extends the existing raw forecast and run tables. It keeps the issue-time key for providers that report issuance. This collector deduplicates by feed, sample point, valid time, and a SHA-256 digest of the validated snapshot. Identical content retains its first receipt time, including when it reappears after a revision. A successful poll may insert zero records. The batch and successful run status commit together.
- APScheduler attempts a poll every five minutes by default, with coalescing and a one-instance limit. A PostgreSQL advisory lock also prevents overlaps with manual requests and other workers. The interval governs polling. Provider data can update on a different cadence. [APScheduler configuration](https://apscheduler.readthedocs.io/en/3.x/userguide.html) · [Open-Meteo model updates](https://open-meteo.com/en/docs/model-updates)
- Network failures and retryable HTTP responses use bounded retries, with a default of three attempts and a 12-second request deadline. A poll validates all five locations before writing any snapshots. Run history records failed polls and a short error reason. The next worker that acquires the lock marks an interrupted run as failed before starting a new run.

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
