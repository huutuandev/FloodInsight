# Dashboard recovery

The Compose database had live Open-Meteo forecast snapshots, but it had never run historical backfill or ETL. The hourly and daily facts, warehouse location and source dimensions, analytics cache, and model registry were empty. A point from the live forecast could populate current weather while the analysis service correctly rejected the same point for ERA5. The dashboard now uses the warehouse's canonical location codes and `open-meteo-archive-era5` coverage to select an initial rainfall window. Explicit location and date filters still apply. The ML panel can retrieve the latest saved output independently of the archive window. The Compose frontend also needed an explicit Next.js development origin for its published loopback address.

## Run recovery explicitly

From the repository root with Compose running, choose a historical period that covers the seasons required for training. On Windows, run:

```powershell
docker compose config --quiet
docker compose up -d --wait
Get-Content -Raw scripts/recover_dashboard.py | docker compose exec -T api-service python - --start 2023-06-01 --end 2024-02-29 --phase all
docker compose ps
```

`--phase data` handles backfill and ETL. It uses the warehouse checkpoints and also loads a recent 30-day window ending six days before the current UTC date. `--phase outputs` verifies rainfall coverage, generates missing analytics, trains only when no valid artifact is registered, and persists model outputs. Repeating the outputs phase reused all three versions and all ten issued predictions/classifications. The pipeline retains missing rainfall as missing and leaves existing provider forecast snapshots intact. Model inference uses the actual recorded archive availability. Historical archive vintages were unavailable, so training and evaluation use the existing chronological retrospective workflow.

## Verified live database on 2026-11-18

The recovery loaded 274 local days from 2023-06-01 through 2024-02-29 and 30 from 2026-10-14 through 2026-11-12 for each of five points. There is a gap between the windows. The hourly and daily rainfall facts had zero null rainfall values in the loaded data, zero duplicate raw observation keys, and no unvalidated foreign keys. No schema migration was required.

| Table | Before | After |
|---|---:|---:|
| `dim_location` | 0 | 5 |
| `dim_weather_source` | 0 | 1 |
| `raw_weather_forecasts` | 250 | 250 |
| `raw_weather_observations` | 0 | 36,490 |
| `fact_weather_hourly` | 0 | 36,480 |
| `fact_rainfall_daily` | 0 | 1,520 |
| `historical_batches` | 0 | 55 |
| `analysis_results` | 0 | 110 (100 recovery, 10 browser-generated) |
| `model_versions` | 0 | 3 |
| `clustering_results` | 0 | 1,520 |
| `prediction_results` | 0 | 5 |
| `classification_results` | 0 | 5 |

## Model evaluation

| Module | Registered version | Observed evaluation |
|---|---|---|
| K-Means | `b997ceaea48249ea852ed69383862844` | 1,370 training rows, silhouette 0.3571, two PCA components explain 77.64% of variance |
| Random forest regressor | `b9c2b33ae5204ce29bcc2fa17ffb8683` | Validation MAE/RMSE 10.093/13.621 mm versus 15.364/20.767 mm persistence. Test 12.399/13.370 mm versus 6.762/12.345 mm persistence |
| Random forest classifier | `fc3d942117074bd988b2c1ad7c30e5a0` | Validation macro precision/recall/F1 0.1364/0.2500/0.1765. Test 0.1538/0.2500/0.1905 |

Each supervised model used 740 training, 220 validation, and 260 test rows. The classifier assigned every test sample to Light Rain. With labels ordered No Rain, Light Rain, Moderate Rain, Heavy Rain, its test confusion matrix was `[[0,75,0,0],[0,160,0,0],[0,20,0,0],[0,5,0,0]]`. All five points returned 6.547 mm and Light Rain for 2026-11-19. The points share very similar ERA5 inputs in this recovery. These outputs are suitable for demonstrating the pipeline. Operational use would require stronger performance and independent evaluation.

## Verification performed

- Ran `docker compose config --quiet`, `docker compose ps`, PostgreSQL read-only integrity queries, and both recovery phases against the running stack.
- Ran pytest separately in each of the seven Python service containers. Final result was 26 passed and 13 skipped. The opt-in database suites were kept off the active database. Live recovery exercised provider requests, persistence, fact generation, analytics, and model training and inference.
- Queried the gateway for Hải Châu daily rainfall for the recent window. The response contained 30 days and totaled 304.3 mm.
- Ran `npm run lint`, `npm run build`, `npm run typecheck`, and the Chromium dashboard test with `DASHBOARD_EXPECT_MODELS=1` and `DASHBOARD_EXPECT_RECOVERY=1`. Chromium passed on the standalone production build and on the rebuilt Compose development frontend.
