# Urban flood probability model evaluation

## Release decision

**Insufficient training data.** The target is observed urban inundation within 50 m of a monitoring point during `(issued_at, issued_at + 24h]`. The training gate stopped before fitting on project data. The primary flood API returns `status=insufficient_training_data` with `flood_probability=null`. The experimental risk index remains available through its separate route. Flood-depth regression was deferred because verified point-level depth labels are unavailable.

| Readiness evidence | Isolated warehouse |
| --- | ---: |
| Documented regional flood events | 1 |
| Candidate high/medium-quality confirmed flood point observations | 0 |
| Candidate dry observations with spatial and 24-hour coverage | 0 |
| Linked candidate event keys with point evidence | 0 |
| Persisted hourly provider forecast snapshots | 0 |
| Monitoring points | 5 |
| ERA5 rainfall-grid groups across the points | 1 |
| Registered flood candidates or approved models | 0 |
| Stored flood probabilities | 0 |

The five points share the ERA5 cell at 16.0° N, 108.25° E. The regional event provides no qualifying observation at a monitoring point. The historical Phase 2 operational audit found 40 unknown point-hour candidates and zero available predictors at issuance. The Phase 3 event replay found 240 unknown candidates. ERA5 receipt delays and the lack of stored forecast vintages prevent an operational hindcast for those periods. [Phase 2 quality report](FLOOD_FEATURES.md), [Phase 3 event replay](artifacts/flood-phase3/historical-validation.json), [Machine-readable Phase 4 readiness](artifacts/flood-phase4/readiness.json)

| Candidate | Actual evaluation on project data |
| --- | --- |
| Class-weighted Logistic Regression | Skipped at readiness gate |
| Balanced-subsample Random Forest | Skipped at readiness gate |
| Class-weighted HistGradientBoostingClassifier | Skipped at readiness gate |
| XGBoost | Excluded. Existing scikit-learn candidates cover linear and nonlinear families without another dependency. |
| Sigmoid and isotonic calibration | Unevaluable with no independent calibration cohort |
| Forecast rainfall-threshold and historical-frequency baselines | Unevaluable with no labeled operational test cohort |

There were **zero evaluated positives and negatives**. Accuracy, balanced accuracy, precision, recall, F1, PR-AUC, ROC-AUC, Brier loss, calibration curve, confusion counts, false alarm rate, event miss rate, per-location performance and uncertainty intervals are all **not estimable**. No new flood Joblib artifact exists. The three existing benchmark Joblib SHA-256 hashes matched their local manifest. The artifact versions remain task-specific: rainfall totals `b9acec0f9d9a45c4a2d5be1fbfc2a2cc`, rain intensity `4c2b0e16158741179517b07147842635`, and daily weather clustering `c8f4d3a249b04c4bae120f2287d105bd`. Their artifacts, registry namespaces, API routes and result schemas are preserved.

## Study and leakage controls

The shared Phase 2 reader extracts data from PostgreSQL in a read-only repeatable transaction. Predictors must be available at issuance and labels must be known by the pinned outcome cutoff. Positives require medium/high confidence with a documented event and qualifying point evidence. Dry targets require affirmative reviewed coverage of the whole unit and window. Unknown, unresolved, late and conflicting labels remain excluded. The study uses one fixed midnight-UTC issuance per nominated point per day, no oversampling, synthetic records or imputation.

The fixed `flood-point-v1` predictors are 24-hour forecast liquid rain, 24-hour recent liquid rain, recent maximum hourly rain, GLO-30 elevation and WorldCover built-up fraction. ERA5 supplies only observed rain received by issuance. Future rainfall requires a complete stored provider vintage. The forecast and observed provider grids must both be identified. Historical reported frequency, modeled soil wetness, offshore conditions and unavailable gauges are outside this v1 predictor set.

The operator pre-registers four disjoint point sets and three chronological cutoffs. The first interval fits estimators, the second fits calibrators, the third selects candidates and alert thresholds, and the final interval is opened only after those choices are locked. Treat that final interval as spent. The gate purges earlier target windows or label evidence touching the next partition, rejects shared event keys and overlapping event windows across partitions, and allows at most one nominated point per transitive weather-grid group. Within a partition, overlapping source event windows are coalesced conservatively before counting. These controls limit reuse of evidence. They cannot establish hydrological independence or representative surveillance by themselves.

| Partition | Documented coalesced positive episode candidates, minimum | Distinct confirmed dry UTC days, minimum |
| --- | ---: | ---: |
| Fit | 20 | 60 |
| Calibration | 10 | 30 |
| Selection | 10 | 30 |
| Test | 10 | 30 |

The initial inventory also requires at least 50 distinct linked event keys before constructing a study. A partition needs 60 days of usable observational span and evidence at every nominated point. The floors are engineering screens and cannot establish statistical adequacy by themselves. A reviewer must check representative wet and dry surveillance, independent storms, source provenance, transferability and calibration. Uncertainty intervals remain null until defensible independent storm and dry sampling blocks are audited.

## Estimation, calibration and evaluation

The Logistic Regression baseline is standardized and class weighted. The forest uses 200 trees, ten-row minimum leaves, fixed seed and balanced subsamples. Histogram gradient boosting uses class weights, fixed seed and no internal random early-stopping split. Sigmoid calibration fits an unweighted logistic transform to held-out raw logits and rejects a non-increasing fitted slope. Isotonic is considered only with at least 1,000 calibration rows, 50 of each class and ten distinct raw scores. No calibration method fits the selection or test partition. [Scikit-learn calibration guidance](https://scikit-learn.org/stable/modules/calibration.html)

Selection minimizes Brier loss among calibrated candidates that beat their own raw classifier on the selection set. Ties favor lower decision cost. The probability threshold is chosen on a fixed 0.00–1.00 grid in 0.01 steps using **5 per missed episode plus 1 per false-alert point-day**. Equal measured costs favor the higher threshold. These costs are explicit engineering choices. The baseline study compares a 100 mm/24 h forecast-rain alert and a historical rate from the fitting cohort with one positive and one negative pseudocount. The frequency model's threshold is also chosen on selection. The rainfall baseline's 0/1 Brier compares its hard alert signal. [Local rainfall reference and limitations](FLOOD_RISK_INDEX.md)

The locked test reports accuracy, balanced accuracy, precision, recall, F1, average precision as PR-AUC, ROC-AUC, Brier score, empirical reliability bins, confusion counts, false-alert and positive-row miss rates, class counts, episode detection and per-location metrics. Event detection requires at least one alert for a qualifying positive row in the episode. Undefined one-class/zero-denominator metrics remain null. The release screen requires lower test Brier than both the raw estimator and historical-frequency baseline, test decision cost no worse than both baselines, detection of at least one event, and at least one supported location. Each served location independently needs five episode candidates, 20 dry days, the same comparative checks and detected event evidence. The final human review records the evidence/report hash and confirms that the surveillance and calibration are defensible.

## Registry, prediction and review

Alembic `0008` extends the model registry with kind `flood` and adds `flood_probability_results` with a kind-constrained version foreign key. The new registry name is `urban-inundation-next-24h`, with artifacts under `/models/flood`. Registry metadata includes feature, target and policy versions, input dataset SHA-256, split coverage, calibration method, threshold, evaluation hash, supported points and the approval record. The existing loader checks filename containment, artifact SHA-256 and compatible scikit-learn version. The inference route requires approved metadata matching the artifact, separate from rainfall prediction and rainfall classification.

| Operation | Prediction service | Gateway |
| --- | --- | --- |
| Training readiness | GET `/flood-prediction/readiness` | GET `/api/v1/flood-prediction/readiness` |
| Calibrated inference | POST `/flood-prediction/predict` | POST `/api/v1/flood-prediction/predict` |
| Separate heuristic assessment | POST `/flood-risk/assessments` | POST `/api/v1/flood-risk/assessments` |

Inference uses a stored artifact and checks its creation and approval time against issue time, the supported point and provider grids, complete receipt-safe features and local tested ranges. It returns a 24-hour validity window, a threshold-based alert class, inputs and quality, model validation/version and limitations. On supported forecasts the probability and per-feature contributions are populated. Each contribution compares the output with a one-feature replacement by that feature's fit-set median. These local comparisons are non-additive and carry no causal interpretation. The API withholds probability on every blocked path; valid probabilities are stored idempotently per version and evidence.

## Reproduce the gate

Run from the repository root against the retained isolated volume. On a database that clears the inventory, `train --study /study.json` expects a mounted study document containing `start`, exclusive `end`, `as_of`, three ordered `cutoffs`, `locations` keyed by `fit`, `calibration`, `selection` and `test`, and a real `surveillance_reference`. The separate operator command `publish VERSION --review /review.json` requires a mounted review containing `review_reference`, matching `surveillance_reference` and `evaluation_sha256`, and `surveillance_and_calibration_reviewed: true`. A passing training run registers a candidate with release status `review_required`.

```powershell
$engine = 'npipe:////./pipe/dockerDesktopLinuxEngine'
docker -H $engine compose -p floodinsight-phase1 up -d --wait postgres
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps warehouse-migrate
docker -H $engine compose -p floodinsight-phase1 up -d --wait --build --no-deps prediction-service api-service
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps prediction-service python -m floodinsight_prediction.flood_training train
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/flood-prediction/readiness'
$body = @{location='hai-chau'; issued_at='2026-11-25T14:00:00Z'} | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/flood-prediction/predict' -Method Post -Body $body -ContentType application/json
docker -H $engine compose -p floodinsight-phase1 run --rm --no-deps -v "${PWD}/services/prediction-service/tests:/app/tests:ro" -e FLOODINSIGHT_RUN_FLOOD_MODEL_INTEGRATION=1 prediction-service python -m unittest discover -s tests -p test_flood_prediction.py
```

Verification passed on PostgreSQL with migration `0008 (head)` and seven tests, including a live gateway request using a legacy rainfall version. The request withheld probability, and subsequent inspection found zero flood prediction rows. The isolated database retained its five risk-index assessments and 120 hourly weather facts. Candidate mechanics were exercised with small test-only arrays in memory. Those checks produced no project-data metrics, registry records or artifacts.
