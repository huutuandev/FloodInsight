# FloodInsight data and dashboard verification

Verified against the existing Compose deployment and PostgreSQL volume on 26 November 2026. Times below use ICT unless marked UTC.

## Root causes

- The forecast collector requested the current point conditions and future hours. It did not request the antecedent hours or hourly soil layers needed for operational assessments. The feature reader also selected historical fallback rows across export windows rather than reading a dedicated recent modeled series at the intended assessment time.
- ERA5 was present in PostgreSQL, but its upstream publication lag made it unsuitable for the preceding 24-hour operational window. The scoring variable for delayed soil is **`soil_moisture_delayed`**, derived from ERA5 `soil_moisture_0_to_7cm`. The live forecast soil variables represent different depth intervals.
- PostgreSQL already had hourly forecast receipts. Earlier assessments filtered receipts at the top of the hour and were generated manually. A usable same-hour receipt could be excluded and the scheduler only collected weather. All running services could report healthy while assessment evidence was unavailable.
- The provider uses hourly UTC interval endpoints. Operational rainfall now uses complete preceding and following UTC hours anchored at the latest whole hour. The actual evidence cutoff and issuance are recorded separately. Historical daily ETL retains Asia/Ho_Chi_Minh day boundaries.
- The runtime had five registered points and nine coordinates defined by the collectors. Backfill registered the additional four, and the dashboard derives the displayed count from the backend. The previous risk engine and Vietnamese text claimed historical calibration despite the absence of eligible flood labels. The previous map also colored road segments and estimated water depth using illustrative thresholds.

## Data sources and provenance

| Source | Verified access and use |
| --- | --- |
| [Open-Meteo Forecast API](https://open-meteo.com/en/docs) | Live hourly Da Nang responses with past hours, future hours, returned grid coordinates and five volumetric soil layers. Operational rain uses total preceding-hour precipitation, which includes convective showers. Per-location receipts preserve the supplied grids and availability. Provider model issuance is unknown and receipt time is the freshness proxy. The [free tier is for evaluation and non-commercial use](https://open-meteo.com/en/pricing). Commercial access uses a subscribed endpoint and API key. |
| [Open-Meteo Historical Weather](https://open-meteo.com/en/docs/historical-weather-api) | Anonymous hourly queries succeeded for ERA5; global 0.25° grid with a documented five-day delay. The application uses a six-day delayed evidence window. The historic rain records retain their original ERA5 schema and provenance. ERA5-Land is hourly at 0.1° with a documented five-day delay and was not substituted for ERA5. |
| [Open-Meteo Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api) | Documentation describes hourly stitched forecasts beginning around 2022 and points to a separate Single Runs API for complete model vintages. No stitched series was used as forecast-time evidence. |
| [Copernicus DEM GLO-30](https://registry.opendata.aws/copernicus-dem/) | Two public 30 m DSM tiles downloaded and validated. Point elevations and 3×3 Horn slopes sampled from the real tiles. |
| [ESA WorldCover](https://esa-worldcover.org/en/data-access) | Public 10 m 2021 v200 classification downloaded and sampled. Built-up fraction uses an 11×11 valid-cell window. CC BY 4.0. |
| [Da Nang digital-services office](https://binhdanhocvuso.danang.gov.vn/cach-theo-doi-tinh-hinh-mua-ngap-tai-da-nang-qua-ung-dung-danang-smart-city/) | Documents city rainfall and inundation coverage through Da Nang Smart City. A licensed machine-readable historical gauge, drainage and flood-surveillance export has not been established for this deployment. |

The workflow reuses the existing weather snapshots and forecast receipt tables, historical warehouse ETL, and terrain and hydrology evidence tables. NASA IMERG and SRTM, GloFAS and OSM drainage distance were not integrated. The existing offshore sea-level series is modeled marine context. No verified river discharge or river gauge time series was imported during this work.

NASA IMERG uses a global 0.1° half-hourly grid. Its Early and Late estimates arrive around four and fourteen hours after observation, respectively. That makes it a candidate for independent regional rain comparison with known latency. GloFAS publishes modeled daily global river discharge at roughly 5 km and requires a local reach match before use. USGS offers global 30 m SRTM through EarthExplorer. This deployment already has verified Copernicus DSM coverage. [NASA IMERG specifications](https://data.nasa.gov/dataset/gpm-imerg-early-precipitation-l3-half-hourly-0-1-degree-x-0-1-degree-v07-gpm-3imerghhe-at--e91fc), [GloFAS output](https://confluence.ecmwf.int/spaces/CEMS/pages/242067364/Model%2BOutput), [USGS SRTM access](https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-shuttle-radar-topography-mission-srtm-1?qt-science_center_objects=0)

## PostgreSQL changes

| Inventory | Baseline | After at verification checkpoint |
| --- | ---: | ---: |
| Registered locations | 5 | 9 |
| Archive raw weather rows | 36,735 | 37,151 |
| Curated hourly weather facts | 36,720 | 37,128 |
| Daily rainfall facts | 1,530 | 1,547 |
| Raw weather snapshots | 600 | 1,698 |
| Hourly forecast snapshot receipts | 2,748 | 5,988 |
| Flood assets | 15 | 25 |
| Terrain values | 25 | 41 |
| Hydrology observations | 264 | 480 |
| Flood risk assessment history | 10 | 39 |
| Point flood outcome labels | 0 | 0 |
| Flood probability results | 0 | 0 |

Live run 33 added 1,089 unique snapshots. Run 34 retained fresh receipt links for unchanged snapshots. Run 37 added nine snapshots and generated nine scores. Historical weather backfill and ETL runs 41–42 added 220 raw records and 216 hourly facts for 20 November. Runs 43–44 added 196 raw records and 192 hourly facts for 14–15 October 2022. ERA5 soil supplied 216 records from nine new assets. DEM and WorldCover added 16 terrain values, covering elevation, slope, center land cover and built-up fraction at the four additional points. The original historical records were retained. Alembic completed successfully at the existing head `0010`. Scheduled updates can advance the live counts.

The registered expansion comprises Sơn Trà, Hòa Phong/Túy Loan, Hòa Bắc and Hòa Khương. Nine locations occupy six returned live weather grid cells. Cẩm Lệ/Ngũ Hành Sơn, Hải Châu/Sơn Trà and Liên Chiểu/Thanh Khê share cells. Seven points share the same ERA5 cell and the two western points add separate ERA5 cells. The additional sites broaden geographic sampling. Shared grids and the absence of independent labeled events prevent an accuracy claim.

## Per-location completeness and freshness

The five baseline assessments each had 15% weighted coverage and lacked `rain_prev_24h_mm`, `rain_max_hour_prev_24h_mm`, `forecast_rain_next_24h_mm` and `soil_moisture_delayed`. The 16:15:53 ICT verification returned all four at all nine locations and 100% weighted coverage. The preceding rainfall and the live soil layers were valid through 16:00 on 26 November. Forecast receipts arrived at about 16:15:52 and the final forecast endpoint was 16:00 on 27 November. The delayed ERA5 soil sample was valid at 16:00 on 20 November and imported around 16:07 on 26 November. The API expires current eligibility when the 24-hour forecast receipt is older than six hours, even if the weather window is still open.

| Monitoring point | Prior 24 h, mm | Peak hour, mm | Future 24 h, mm | Delayed soil, m³/m³ | Risk score | Category | Stored ID |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Cẩm Lệ | 36.5 | 8.2 | 21.4 | 0.288 | 32.90 | Moderate | 87 |
| Hải Châu | 34.2 | 5.0 | 26.1 | 0.288 | 29.86 | Moderate | 88 |
| Hòa Bắc | 22.2 | 2.8 | 28.4 | 0.333 | 21.07 | Low | 89 |
| Hòa Khương | 24.6 | 6.4 | 18.2 | 0.493 | 23.89 | Low | 90 |
| Hòa Phong | 21.4 | 5.4 | 21.3 | 0.288 | 28.12 | Moderate | 91 |
| Liên Chiểu | 23.2 | 3.2 | 27.2 | 0.288 | 29.34 | Moderate | 92 |
| Ngũ Hành Sơn | 36.5 | 8.2 | 21.4 | 0.288 | 28.47 | Moderate | 93 |
| Sơn Trà | 34.2 | 5.0 | 26.1 | 0.288 | 29.21 | Moderate | 94 |
| Thanh Khê | 23.2 | 3.2 | 27.2 | 0.288 | 30.52 | Moderate | 95 |

Every row also had 1-, 3-, 6-, 12-, 48- and 72-hour recent rain, maximum 3-hour accumulation, 6- and 12-hour forecast rain, five live soil layers, elevation, slope and built-up fraction. Missing context still includes verified drainage distances, local river levels and discharge, and independently reviewed point flood observations.

## Automation and execution

- The existing APScheduler collector starts after the warehouse and prediction services are healthy. The default live interval is five minutes. The archive check starts at service startup and then runs hourly by default. It skips dates with an already complete ERA5 day. Both jobs coalesce pending runs. PostgreSQL advisory locks prevent concurrent collection and archive refreshes across processes.
- Final startup logs recorded `already_collected` for the 20 November soil archive. Scheduled live run 38 completed at 16:19:43 ICT, added zero unique weather snapshots, and generated nine scored assessments. It recorded new receipt links for the weather values it actually received. The upstream model timestamp remained unavailable.
- The gateway and frontend proxy integration suite passed assessment generation, exact replay, persisted assessment history, historical rainfall, model training and inference abstention, and the restriction on browser-proxy model training.
- Unit verification passed three Open-Meteo ingestion tests, nine flood feature tests and seven flood risk tests. Two older isolated-stack tests were skipped by their environment gate. Compose health checks, the existing Alembic migration job, lint, TypeScript checking and the optimized Next.js build completed.
- The current terrain research endpoint returned nine complete profiles, zero excluded and an in-sample Silhouette Score of 0.460. It describes exploratory terrain similarity.

## Risk methods and model validation

The base experimental heuristic uses fixed weights of 40% upcoming precipitation, 20% preceding rainfall, 15% peak hourly rainfall, 15% terrain and 10% delayed soil. The linear ramps clip at 0–100 mm for both 24-hour rainfall totals, 0–50 mm for the peak hour, 0–20 m for inverted elevation, 0–1 for built-up fraction and 0.20–0.50 m³/m³ for ERA5 soil. Terrain is the mean of normalized elevation and built-up fraction. Category boundaries are 25, 50 and 75 points. All four non-soil factors are required.

`flood-risk-v1-modeled` uses the receipt-safe operational weather series and a complete single forecast receipt per horizon. The public flood-risk index has a 24-hour weather window. The 6- and 12-hour values show rainfall accumulation. When only delayed soil is absent and at least 90% of the configured weight is present, the separately versioned `-limited` method reports the fixed-weight subtotal. At default weights it has a maximum of 90 points and discloses the absent factor. The coverage denominator stays fixed. Terrain profiles remain exploratory and do not produce a standalone forecast.

The training implementation has logistic regression, random forest and an optional XGBoost candidate. Registry records for legacy rainfall prediction, classification and clustering are separate. The flood training gate requires individually linked flood episodes and explicit monitored dry periods, chronological partitions and independent spatial/episode splits. The evaluated probability must also pass calibration and release gates. No flood classification performance or street-scale inference is supported by a terrain cluster.

XGBoost 2.1.4 is installed in the running prediction container. The training and inference endpoints returned `insufficient_training_data`. Readiness reported one documented regional event, zero linked episode keys, zero candidate positive point labels, zero candidate dry labels and zero registered flood artifacts. The minimum episode counts for fit/calibration/selection/test are 20/10/10/10 and the minimum monitored dry days are 60/30/30/30. Precision, recall, F1, balanced accuracy, PR-AUC, ROC-AUC, Brier score, calibration, false-alarm and miss rates, and the confusion matrix remain unavailable.

## October 2022 flood

On 14–15 October, local reporting documented flooding around the Túy Loan market in Hòa Phong. A separate report recorded water above 12 m at the Nam Mỹ weir during overtopping. These observations describe their reported sites. The case view reads the selected point's actual ERA5 daily rows. Hải Châu returned 179.5 mm on 14 October and 37.0 mm on 15 October with 24/24 hours each. Its terrain values are present-day reference covariates. There is no event-complete forecast-time vintage and independent point-outcome set for a retrospective flood score or a claim of successful prediction. [Local flood and rainfall report](https://baodanang.vn/ve-tran-mua-lich-su-ngay-14-10-2022-o-da-nang-3235019.html), [Nam Mỹ weir report](https://baodanang.vn/rut-kinh-nghiem-van-hanh-dap-dang-nam-my-3161189.html)

## Modified components

- `docker-compose.yml`, `.env.example` and the ingestion configuration, schema, provider adapter, scheduler and ingestion orchestration add operational weather, delayed soil refresh and downstream assessment/inference.
- Shared `flood_features.py`, `flood_store.py`, `flood_risk.py` and prediction `routes/flood_risk.py` implement receipt-safe evidence selection, explicit method versions, fixed weights, freshness and historical replay. Clustering `routes/flood_profiles.py` uses the latest terrain evidence for its live research view.
- Warehouse `routes/historical.py`, `flood_data.py`, `services/flood_rasters.py` and `scripts/bootstrap_floodinsight.py` refresh delayed soil and cover both DEM tiles.
- Dashboard layout, stylesheet, risk panels, research/operations panels and Vietnamese dictionary expose resident-oriented status, point comparisons, practical guidance, technical disclosure, a point-marker map and historical evidence. Legacy rainfall evaluation is in a separate research disclosure.
- The ingestion, feature, risk, gateway/proxy and browser suites cover the updated live and replay contracts.

## Remaining gaps

- Acquire reviewed georeferenced positive flood observations and monitored non-events with temporal and spatial coverage. An official public case description alone cannot label the monitoring points.
- A licensed local gauge and drainage feed is still needed to measure recent rainfall and improve hydrological attribution. The live rain and soil inputs are modeled and the delayed soil is reanalysis.
- No supported whole-city or street inundation area, water depth, route safety, or sub-24-hour flood event forecast was published. The short-horizon rainfall totals are available.
- The existing recovery controls are reachable on the localhost deployment. Role-based authentication would be needed before exposing them to a wider audience.

## Reproducible startup and recovery

```powershell
docker compose up -d --build --wait
docker compose ps -a
docker compose logs warehouse-migrate
Invoke-RestMethod -Method Post http://localhost:8001/ingestion/run
Invoke-RestMethod -Method Post http://localhost:8002/warehouse/flood-soil/refresh
Invoke-RestMethod http://localhost:8000/api/v1/flood-risk/latest
npm.cmd --prefix frontend run test:flood-api
npm.cmd --prefix frontend run test:dashboard
```

Use `python scripts/bootstrap_floodinsight.py --start 2022-10-14 --end 2022-10-15` for additive archive and terrain recovery where local Python and Docker are installed. The older records remain accessible by point, source and date. Recovery does not require resetting the volume or training a classifier.
