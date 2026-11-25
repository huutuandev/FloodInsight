# Experimental Flood Risk Index for Da Nang

`flood-risk-v1` is a configurable 0–100 screening index for a 24-hour forecast horizon at a canonical monitoring point. The value expresses the combination of available hazard and susceptibility factors under the rules below. It has no frequency or probability interpretation. The API and the PostgreSQL table always require `flood_probability = null`. The 50 m study radius describes point evidence matching. It does not increase the resolution of gridded weather or establish district-wide coverage.

## Evidence and parameters

Da Nang's 2025 disaster response plan puts 100–200 mm/24 h at the lower end of a **regional heavy-rain** response scenario, with additional duration and administrative coverage conditions. The plan separately identifies urban flooding hotspots. The national October 2022 report documents much larger station totals during the verified event, including 637 mm in 24 hours at Đà Nẵng station. These references support local context for a rainfall scale, but do not supply an inundation response curve or valid hourly threshold at the five project points. The city's response discussion explicitly calls for mapping site-specific rain, depth and duration. [Da Nang 2025 plan, heavy-rain section](https://pctt.danang.gov.vn/Portals/0/2025_%20UBND%20TP%20QD%201657%20phe%20duyet%20PHUONG%20AN%20UNG%20PHO%20THIEN%20TAI%20TREN%20DIA%20BAN%20THANH%20PHO.pdf), [National October 2022 event report](https://phongchongthientai.mard.gov.vn/Pages/bao-cao-nhanh-cong-tac-truc-ban-pctt-ngay-14-10-2022.aspx), [Municipal flood-response discussion](https://cttdt.danangportal.gov.vn/vi/web/dng/w/thuc-hien-cac-giai-phap-phong-chong-mua-lon-ngap-lut-tren-dia-ban-thanh-pho-i)

| Factor | Input and normalization anchors | Default weight and justification |
| --- | --- | --- |
| Forecast rainfall | 0–100 mm of liquid rain over next 24 h from one recorded Open-Meteo receipt/run. Use the lower regional response anchor as the high endpoint; a score cap is an engineering choice, not an inundation trigger. | **0.40**. Largest individual weight to make future rainfall the primary near-term driver for this forecast product. |
| Recent accumulation | 0–100 mm over past 24 complete hours, with actual archive receipts and Phase 2 lineage checks. Use the same 24-hour local context anchor to keep rainfall amounts comparable. | **0.20**. Add recent loading without giving the same aggregate the same weight as forecast rain. |
| Recent hourly intensity | 0–50 mm for the wettest hour of the last 24 hours. The cap is an experimental stress-test anchor below the 71 mm peak described for one 2023 Da Nang station in the national disaster white paper. It does not represent the capacity of the drainage network. | **0.15**. Represents short bursts while acknowledging overlap with the recent total. [National 2023 disaster white paper](https://phongchongthientai.mard.gov.vn/FileUpload/2024-05/Hpk9nDyULkuEzfd500.%20S%C3%A1ch%20tr%E1%BA%AFng%20n%C4%83m%202023%20%28full%29.pdf) |
| Terrain susceptibility | Equal average of inverted GLO-30 elevation ramp (0–20 m EGM2008) and WorldCover 2021 built-up fraction (0–1). The elevation endpoints bracket the five sampled DSM heights (8.45–12.20 m) with headroom; they are not flood levels. The land-cover endpoints are natural fraction bounds; the value is not measured imperviousness. Half the factor is allocated to each proxy because no performance evidence can rank the two. | **0.15**. Static secondary context with no site hydraulic model. |
| Soil wetness | ERA5 volumetric moisture (0–7 cm) on the Phase 2 delayed window, 0.20–0.50 m³/m³. This broad engineering ramp lies within the observed Phase 2 sample range (0.062–0.511) and illustrates sensitivity. Without field capacity, porosity or local fit, the feature measures modeled wetness and cannot establish saturation. | **0.10**. Secondary context with limited independence, coarse shared grid and at least six days of lag in this feature. |

For higher-is-worse inputs, normalize as `clip((value - low) / (high - low), 0, 1)`. Invert only elevation. The zero anchors for rainfall represent zero measured liquid rain and the upper anchors saturate the ramp. The score is `100 × Σ(weight × normalized factor) / Σ(present weight)`. Each displayed contribution uses the same denominator. Weighting is an explicit engineering judgment, with 75% assigned to rain as a group. The total and hourly peak are correlated, so separate terms should not be read as independent evidence. The linear, clipped min–max transformation and one-at-a-time sensitivity follow composite-indicator guidance. The weights and boundaries were not learned, calibrated or locally validated. [OECD/JRC composite-indicator handbook](https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf)

River stage/discharge, historical point susceptibility, terrain slope as a signed risk term and offshore sea level are excluded from scoring. The warehouse lacks a verified local reach/gauge relationship, qualifying point-level flood history with a surveillance denominator, a validated direction for DSM slope, and a local tide-to-site hydraulic transfer or common vertical datum. Slope and offshore context remain in the feature warehouse. An area event record cannot take the place of point evidence.

### Data sufficiency and interpretation

All rainfall factors and both terrain inputs are mandatory. With defaults, soil wetness alone may be missing, leaving 0.90 of nominal weight and a clearly marked `limited` assessment. That score uses a re-normalized denominator. Other missing critical inputs, late inputs or insufficient nominal coverage produce `Insufficient Data` and a null index. Contributions are unset in an abstention, although available factor values and normalization are returned for diagnosis. No imputation is used.

| Index | Category |
| --- | --- |
| 0–<25 | Low |
| 25–<50 | Moderate |
| 50–<75 | High |
| 75–100 | Very High |
| null | Insufficient Data |

These are equal-width display bands and do not correspond to the municipal disaster levels or evacuation thresholds. The index uses the Phase 2 hourly UTC decision convention and recorded source availability. Grids and effective resolution are returned, and freshness distinguishes receipt/as-of availability from first and last evidence validity. Static receipt dates document availability, while the source definition identifies the product vintage. A missing-value or stale-receipt explanation must remain visible when interpreting a score or abstention.

### Configuration, API and persistence

The defaults are defined in `services/ml-common/floodinsight_ml/flood_risk.py:RiskConfig`. Use `FLOODINSIGHT_PREDICTION_FLOOD_RISK_CONFIG` inside the prediction container or process to point to a mounted JSON override. Omitted top-level keys inherit defaults. Supply a complete weights or ramps object when overriding it, use finite and ordered numeric anchors, and give deployments with changed policy a new method version. The configuration hash is included alongside the version. [Example requiring all factors](config/flood-risk.example.json)

| Action | Direct service | Gateway |
| --- | --- | --- |
| Create/replay assessment | Prediction `POST /flood-risk/assessments` | `POST /api/v1/flood-risk/assessments` |
| List results, optionally filtered by `location` and `limit` | Prediction `GET /flood-risk/assessments` | `GET /api/v1/flood-risk/assessments` |
| Explore terrain feature profiles | Clustering `GET /clustering/flood-profiles` | `GET /api/v1/clustering/flood-profiles` |

The request body is `{"location":"hai-chau","issued_at":"2026-11-25T14:00:00Z"}`. Issuance defaults to the most recent whole UTC hour. A requested issue must be at or before the current time. POST persists both scores and abstentions. Migration `0007` adds `flood_risk_assessments` with a location FK, feature and method versions, full configuration and evidence JSON, and a stable evidence fingerprint. An identical location/issuance/configuration/evidence replay returns the same ID. A changed configuration or evidence produces a distinct stored revision. See the Phase 2 warehouse source for lineage and timestamp rules.

Clustering is a separate exploratory output. It uses standardized GLO-30 elevation, GLO-30 slope and WorldCover built-up fraction across complete points at one issuance. K-Means uses 20 initializations and a fixed random seed. It requires at least twice as many distinct complete profiles as requested groups. The service reports group sizes, assignments and in-sample silhouette. It excludes shared-grid rain and soil from this spatial demonstration. Cluster IDs carry no severity order or confirmed flood meaning. The existing daily weather clustering is unchanged.

## Reproducible verification

Use the retained Phase 1 data volume and the engine syntax for this workstation. Start only the required services.

```powershell
$engine = 'npipe:////./pipe/dockerDesktopLinuxEngine'
docker -H $engine compose -p floodinsight-phase1 up -d --wait postgres
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps warehouse-migrate
docker -H $engine compose -p floodinsight-phase1 up -d --wait --build --no-deps prediction-service clustering-service api-service
$body = @{ location = 'hai-chau'; issued_at = '2026-11-25T14:00:00Z' } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/flood-risk/assessments' -Method Post -Body $body -ContentType application/json
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/flood-risk/assessments?location=hai-chau'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/clustering/flood-profiles?issued_at=2026-11-25T14%3A00%3A00Z&clusters=2'
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps -v "${PWD}/services/ml-common:/opt/ml-common:ro" -v "${PWD}/services/warehouse-service/tests:/app/tests:ro" -e PYTHONPATH=/opt/ml-common:/app -e FLOODINSIGHT_RUN_RISK_DB_TESTS=1 warehouse-service python -m unittest discover -s tests -p 'test_flood*.py'

function Invoke-WarehouseModule {
    docker -H $engine compose -p floodinsight-phase1 run -T --rm --no-deps -v "${PWD}/services/ml-common:/opt/ml-common:ro" -e PYTHONPATH=/opt/ml-common:/app warehouse-service python -m @args
}
$eventWindow = Invoke-WarehouseModule floodinsight_warehouse.flood_dataset --mode operational --start 2022-10-13T17:00:00Z --end 2022-10-15T16:00:00Z --as-of 2026-11-25T14:00:00Z
$eventWindow | docker -H $engine compose -p floodinsight-phase1 run -T --rm --no-deps -v "${PWD}/services/ml-common:/opt/ml-common:ro" -e PYTHONPATH=/opt/ml-common:/app warehouse-service python -m floodinsight_ml.flood_risk_validation -
```

## Historical validation and sensitivity results

The October 14–15, 2022 Vietnam-local event window yields **240 point-hour candidates** (48 decision hours × five points). Every candidate had an unknown point label and the index abstained for all 240. There were zero scoreable labeled rows and zero scoreable event keys. Detection sensitivity, specificity, precision, and event hit counts are undefined. The one officially documented event establishes regional occurrence, but no 50 m point/time label qualifies and the warehouse has no operational forecast vintages for this event. The backtest counts numbers of labels and abstentions separately, computes a confusion matrix only for scored confirmed labels, and uses High/Very High as its experimental alert rule. Event-key counts remain descriptive and cannot substitute for independent storm validation. [Machine-readable historical validation and sensitivity report](artifacts/flood-phase3/historical-validation.json)

With no scoreable real rows, the sensitivity harness uses three explicitly illustrative complete factor vectors. These vectors are mathematical probes and are neither measurements nor stored assessments. It perturbs one scored weight or one normalization span by ±20% per trial. Perturbed weights are normalized over the same present factors. Each span changes around its fixed low anchor, with elevation still inverted. Bands and coverage rules are held fixed. These intervals quantify sensitivity to the chosen parameters, separately from uncertainty in inputs or flood probability.

| Illustrative profile | Baseline | Range over 22 trials | Categories |
| --- | ---: | ---: | --- |
| Lower rain | 18.04 | 16.92–19.04 | Low |
| Near boundary | 49.18 | 46.18–53.68 | Moderate, High |
| Large rain | 93.21 | 88.21–95.21 | Very High |

The near-boundary probe changes category under the tested perturbations. Scored API assessments expose the same diagnostic. An abstention has null sensitivity because no index is available to perturb.

On the retained dataset, the API persisted one assessment per monitoring point for November 25, 2026 at 14:00 UTC (21:00 Vietnam time). All five returned `Insufficient Data`, with 0.15 nominal weight coverage from terrain and null index and probability. Neither a complete recent rain window nor an available stored 24-hour forecast existed for the issuance. The clustering route processed all five static profiles into groups of four and one with in-sample silhouette 0.297. The singleton and small sample preclude stable cluster interpretation.

Migration `0007 (head)` and 23 tests passed, including gateway-to-PostgreSQL creation, idempotent replay, retrieval, invalid issue rejection and exploratory clustering. A historical rainfall gateway query still returned 73.6 mm over 24 valid hours for Hải Châu on October 13, 2023. The Phase 2 retrospective export was reproduced byte for byte after sharing its feature reader with the services.
