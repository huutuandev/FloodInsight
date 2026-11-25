# Flood feature engineering and dataset construction

`flood-point-v1` produces one row per canonical monitoring point and UTC-hour decision time. The builder reads the warehouse in a read-only repeatable transaction, exports a versioned feature and unit map, and includes source row identifiers, the latest availability time used by each feature, and the contributing weather grid and valid times. The feature engine lives in `services/ml-common/floodinsight_ml/flood_features.py`. The warehouse CLI and SQL live in `services/warehouse-service/floodinsight_warehouse/flood_dataset.py`. The existing daily rainfall ML code and this builder share the ERA5 availability calculation in `availability.py`.

## Target and evidence

The primary target is urban inundation observed during the next **24 hours**, `(issue, issue + 24h]`, within **50 m of the canonical WGS84 sampling point**. An observation linked to a verified event represents local inundation when its confidence is high or medium, its mapped point and full uncertainty radius lie within the 50 m unit, and its timestamp falls within both the documented event window and the target window. An inundation event is a source-documented episode linked to qualifying point evidence of temporary floodwater. Rainfall intensity, forecast runoff and regional event reports cannot establish the target. The 50 m rule is a Phase 2 study convention and does not define a district, drainage basin or pixel. Positive timestamps use zero temporal tolerance and require an actual observation time and location link.

| Output | Evidence required |
| --- | --- |
| `positive` / 1 | At least one qualifying flood observation and a documented event. Copies of a single event can support multiple rows and are counted together. |
| `negative` / 0 | Affirmative high/medium-quality dry coverage across the entire 24-hour interval and spatial unit, with a coverage reference and a reviewed spatial coverage radius. The usable radius must cover the point unit after subtracting offset and uncertainty. |
| `unknown` / null | Open horizon, unobserved/low-quality evidence, insufficient spatial or temporal coverage, late evidence, or conflicting positive and negative coverage. |

Alembic `0006` adds optional reviewed coverage start, end and radius on existing observations. Older dry records without these fields remain ineligible. A positive or negative row exports confidence, observation IDs and the earliest eligible label availability time, bounded below by target close. `--as-of` freezes the latest permissible evidence receipt and must be set to a fixed instant for replay. Event evidence received after the decision may qualify as a target after horizon close. The same evidence cannot become a predictor for that decision. Shorter **target** horizons are deferred until qualifying data exist. Forecast extract windows of 6 and 12 hours are predictors for the 24-hour target.

## Feature definitions

All windows use complete UTC hours. The rainfall archive exposes preceding-hour accumulation at the interval end. The feature extractor joins that raw record to the corresponding hour-start fact, verifies liquid rain in millimetres and checks agreement with the deterministically rounded fact. Null measurements or missing bins invalidate the affected window. A measured zero remains zero.

| Features | Units | Definition and source |
| --- | --- | --- |
| `rain_prev_{1,3,6,12,24,48,72}h_mm` | mm | Sum of one consistent archive product over the complete hour bins immediately preceding issue. Requires all bins and as-of availability. |
| `rain_max_hour_prev_24h_mm` | mm | Largest hourly accumulation over the last 24 complete hours. |
| `rain_max_3h_prev_24h_mm` | mm | Largest sum over any run of three adjacent hours fully contained in the prior 24 hours. |
| `wet_hour_intensity_prev_24h_mm_per_h` | mm/h | Mean hourly accumulation during wet hours, where wet means at least 0.1 mm. Null when the 24-hour window is complete but dry. |
| `wet_hours_prev_24h`, `longest_wet_spell_prev_24h` | h | Count of wet hours and longest uninterrupted wet spell in the complete prior 24-hour window. |
| `antecedent_rain_delayed_{24,72}h_mm` | mm | 24- or 72-hour archive accumulation ending six days before issue. This is a delayed antecedent covariate. |
| `forecast_rain_next_{6,12,24}h_mm` | mm | Sum of one-hour liquid rain from the newest eligible single receipt/run among stored hourly Open-Meteo forecast snapshots. Requires a complete single-grid horizon and preserves the constituent snapshot IDs. Deduplication in the source feed may leave later runs incomplete. |
| `soil_moisture_delayed` | m³/m³ | Latest 0–7 cm modeled ERA5 sample in the 24 hours ending six days before issue, with an availability check. |
| `elevation_m`, `surface_slope_deg` | m, degree | Copernicus GLO-30 surface elevation in EGM2008 and Phase 1 Horn slope at the exact canonical point. The coarser GLO-90 measurements remain a separate source. |
| `land_cover_class`, `built_up_fraction` | ESA class code, 0–1 | WorldCover 2021 center class and fraction of built-up cells in the Phase 1 11×11 neighborhood. The fraction is a land-cover proxy. |
| `offshore_sea_level_msl_m` | m relative to global mean sea level | Latest offshore modeled sea-level value valid within the preceding six hours and received by issue. Shared regional context only. It includes tides and other ocean effects and supplies no site or river-stage measurement. |
| `reported_flood_events_prev_365d` | count | Distinct qualifying event keys observed and known strictly before issue in the preceding 365 days. No qualifying evidence yields null. A reported count cannot estimate a flood rate without a surveillance denominator. |

River and drainage distance, discharge, local water level and network capacity have no verified data in this warehouse. They are excluded from v1. Static terrain and land cover require their recorded asset receipt even in retrospective mode. Version the schema again if units, windows, source matching or label semantics change.

## Availability and evaluation rules

- **Operational replay** requires recorded source receipt by the decision time. An archive hour also has to have ended. Forecast values must come from the raw forecast feed, be valid in the future horizon, and have a single stored receipt/run. When model initialization is present it must precede receipt. Open-Meteo's stitched feed has no guaranteed initialization timestamp. The receipt is the as-of boundary, and a sample row represents a replay decision time rather than proof a flood forecast was issued. The CLI supports whole UTC hours to avoid treating partial hourly rain bins as exact totals.
- **Retrospective** assumes archive availability six days after an hour ends, as in the existing daily workflow's calendar-level delay policy. It uses stored reanalysis revisions and cannot establish which version was public at the historical time. It suppresses forecast rain and modeled marine features and uses actual asset receipt for static data and label evidence. Keep these artifacts out of operational evaluation.
- Feature provenance is a separate object for auditing. It contains source identifiers and availability, and must be excluded from predictor matrices alongside target/evidence metadata. No imputing, fitting, normalization, or training occurs in the builder.
- Shared rainfall grids are grouped transitively across points. The report separately counts distinct contributing grid-time pairs and pairs used across multiple points. Region-wide ocean context is also counted as shared when used. Point rows and repeated decisions around the same event cannot be treated as independent replicates.
- `validate_holdout` checks supervised candidate partitions. It rejects unknown labels, unresolved training targets or evidence overlapping the first evaluation issuance, common points or rainfall-grid groups, common event keys, and overlapping documented event episodes. Use additional event review for independent storms and fit any future preprocessing solely on training rows. Current data support no split.

## Reproduce

Use the already collected Phase 1 volume. In PowerShell, select the Docker Desktop engine if required. The sample uses the existing warehouse image with the shared feature package mounted read-only. It starts PostgreSQL only and applies the additive migration. The output files contain the version, units, exact parameters, build mode, row SHA-256, quality report and rows. Use `--report-only` to omit the rows from stdout while retaining the checks and hash.

```powershell
$engine = 'npipe:////./pipe/dockerDesktopLinuxEngine'
docker -H $engine compose -p floodinsight-phase1 up -d --wait postgres
docker -H $engine compose -p floodinsight-phase1 build warehouse-service warehouse-migrate
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps warehouse-migrate

function Invoke-FloodDataset {
    docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps -v "${PWD}/services/ml-common:/opt/ml-common:ro" -e PYTHONPATH=/opt/ml-common:/app warehouse-service python -m floodinsight_warehouse.flood_dataset @args
}

Invoke-FloodDataset --mode retrospective --start 2023-10-19T17:00:00Z --end 2023-10-20T00:00:00Z --as-of 2026-11-25T13:59:00Z
Invoke-FloodDataset --mode operational --start 2023-10-19T17:00:00Z --end 2023-10-20T00:00:00Z --as-of 2026-11-25T13:59:00Z --report-only
Invoke-FloodDataset --mode operational --start 2026-11-25T14:00:00Z --end 2026-11-25T14:00:00Z --as-of 2026-11-25T14:00:00Z
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps -v "${PWD}/services/ml-common:/opt/ml-common:ro" -v "${PWD}/services/warehouse-service/tests:/app/tests:ro" -e PYTHONPATH=/opt/ml-common:/app warehouse-service python -m unittest discover -s tests -p 'test_flood*.py'
```

Commands must use a timezone-aware ISO 8601 timestamp. The inclusive issuance range accepts up to seven days per call. `--as-of` is independently specified and can be later than the target horizon when verified after the fact. Capturing an immutable database snapshot or retaining the resulting hash and export is necessary when later source revisions or backfills could alter the replay.

## Observed data quality

| Export | Point-hour rows | Positive / negative / unknown | Available feature coverage |
| --- | ---: | ---: | --- |
| [October 2023 retrospective](artifacts/flood-phase2/retrospective.json) | 40 | 0 / 0 / 40 | Delayed soil moisture 40/40, range 0.062–0.511 m³/m³. Delayed 24-hour rain 5/40, all 73.6 mm. Other features 0/40. |
| [October 2023 operational replay audit](artifacts/flood-phase2/operational-historical-quality.json) | 40 | 0 / 0 / 40 | Every feature unavailable at issuance. The archive hours were collected in November 2026. |
| [November 25, 2026 operational sample](artifacts/flood-phase2/operational-current.json) | 5 | 0 / 0 / 5 | Elevation, slope, land-cover class, built-up fraction and offshore sea level available at all five points. Other features unavailable. The 24-hour target was open at the export cutoff. |

The exports span the five existing monitoring points. The October window covers eight consecutive hourly decisions from October 19 at 17:00 UTC to October 20 at 00:00 UTC, 2023. The current sample uses November 25, 2026 at 14:00 UTC (21:00 Vietnam time). GLO-30 elevations span 8.45–12.20 m and slopes 0.22–6.56°. WorldCover supplied four class-50 point samples and one class-10 sample. The marine input was 1.49 m at one offshore grid and hour, shared across all five rows.

There were zero duplicate point-issuance rows, zero candidate duplicate flood observations, and zero independently evidenced flood episodes in every export. The positive fraction among known labels is undefined. The archive inventory has 125 raw observations for 25 grid-valid timestamps on one ERA5 cell. The retrospective features used 30 distinct grid-valid pairs, all shared by multiple points, and the current sample used one shared marine pair. The five points form one rainfall-grid holdout group.

A repeat export of the retrospective dataset produced the same bytes. The machine-readable reports include per-feature missing percentages, distributions, availability counts and provenance. Migration 0006 and 14 Phase 1/2 tests were verified on the isolated warehouse.

## Supervised training readiness

**Blocked.** Phase 1 contains one documented regional event with no qualifying point observations, and no verified dry point coverage. It also has no persisted forecast snapshots. Live forecast probes documented in Phase 1 were validation in memory. All five original points fall in one ERA5 grid group. No labels were inferred from rain, the documented regional report, or missing data. Continue collecting documented wet and dry coverage, preserving complete forecast vintages, and validating additional independent weather grids and flood events before supervised training.
