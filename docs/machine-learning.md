# Machine-learning services

FloodInsight has three separate FastAPI services. Each reads the ERA5 source in PostgreSQL and uses its own Joblib volume. The warehouse's migration `0004` extends the existing result tables with model metadata, cluster projection details, and class probabilities. Model versions record the input scope, features, dataset sizes, evaluation, scikit-learn version, and artifact checksum. Results endpoints read PostgreSQL. Inference loads an existing artifact. Training starts only through a call to a `/train` endpoint.

## APIs and regeneration

| Service | Default loopback port | Train | Inference | Read |
| --- | ---: | --- | --- | --- |
| Clustering | 8004 | `POST /clustering/train` | `POST /clustering/run` | `GET /clustering/results`, `GET /clustering/metrics` |
| Prediction | 8005 | `POST /prediction/train` | `POST /prediction/predict` | `GET /prediction/results`, `GET /prediction/metrics` |
| Classification | 8006 | `POST /classification/train` | `POST /classification/predict` | `GET /classification/results`, `GET /classification/metrics` |

Train requests accept `start_date`, `end_date` and optional `location`. Omitting the location pools available locations. Clustering also accepts `clusters` (default 3). Supervised training accepts `availability` (`recorded` by default, or `retrospective`). Classification accepts a `thresholds` object. Next-day inference accepts `location`, optional `version`, and optional timezone-aware `issued_at`. When omitted, the newest version or current issuance time is used. The target is the next Vietnam-local calendar day. Results and metrics accept `version`. Results also accept `limit` and `offset`.

To regenerate deleted results, keep the same model version and artifact. For clustering, repeat `/run` with the original location and date window. For a next-day result, replay `/predict` with the original location, version, and returned `issued_at`. Each call upserts its result key. Issue times must be between model creation and the present. Artifacts in the three model volumes and the corresponding database rows must be retained together.

## Clustering

A sample is a location-day with complete liquid-rainfall coverage. The six features are total rainfall, mean positive-hour rainfall intensity, rainy-hour count, and mean humidity, temperature, and wind. For a fully observed dry day, intensity is defined as zero. Missing weather features use fitted medians. K-Means uses standardized features, with PCA fit to the same scaled data for two-dimensional visualization. The run response includes an ECharts scatter option. Metrics include the silhouette score and per-cluster means in the original units.

## Prediction and classification

The supervised models use rainfall from target days minus 8, 9, and 10; mean rainfall from days minus 8 through minus 14; temperature, humidity, and wind from day minus 8; and sine and cosine calendar seasonality. All seven lag days require complete rainfall and availability by issuance. Labels are complete daily liquid-rainfall totals. The same dates stay together across locations when splitting chronologically. Train and validation cutoffs exclude labels unavailable by the next split's first issue time. Median imputation for missing weather values is fitted only on training data. No rainfall is imputed.

Recorded availability uses the latest raw receipt for each day. Retrospective evaluation uses an explicit six-day publication assumption after the local day ends. It evaluates event-time chronology with a lag and does not establish which ERA5 revision existed at each past issuance. Prediction and classification APIs always enforce recorded receipt times, including when serving a model trained in retrospective mode. A single recent archive backfill cannot supply the recorded availability needed to train or verify earlier forecasts. Missing lag days cause HTTP 422. [Open-Meteo historical data and publication delay](https://open-meteo.com/en/docs/historical-weather-api)

XGBoost regression compares MAE and RMSE with a persistence baseline using the most recent eligible rain lag, day minus 8. Classification uses a separate XGBoost model with class-balanced sample weights. Retrain artifacts created with a different feature list before requesting new predictions. The default classes are project-defined daily intensity categories:

| Class | Daily rainfall |
| --- | --- |
| No Rain | Less than 0.1 mm, including trace amounts |
| Light Rain | 0.1 to less than 10 mm |
| Moderate Rain | 10 to less than 25 mm |
| Heavy Rain | 25 mm or more |

Configure the lower boundaries as `thresholds.light_mm`, `thresholds.moderate_mm`, and `thresholds.heavy_mm` when training. All four classes must occur in the training split. Confusion matrices use the class order above, with actual class on rows and predicted class on columns. The classifier returns uncalibrated class scores. Flood forecasting would require reliable flood-event labels and a separate evaluation.

## Historical random forest benchmark

Validation used real Hải Châu ERA5 data from 2023-06-01 through 2024-02-29 in an isolated PostgreSQL 16 database. Clustering used 274 complete daily rows. The silhouette score was **0.3514** for three clusters of **44, 133, and 97 days**. The first two PCA components explained **54.02% and 23.61%** of scaled feature variance.

Both retrospective supervised models used the following partitions after the lag and embargo filters:

| Split | Samples | Target dates |
| --- | ---: | --- |
| Train | 148 | 2023-06-15 to 2023-11-09 |
| Validation | 44 | 2023-11-18 to 2023-12-31 |
| Test | 52 | 2024-01-09 to 2024-02-29 |

| Regression | Validation MAE | Validation RMSE | Test MAE | Test RMSE |
| --- | ---: | ---: | ---: | ---: |
| Random forest | 9.80 mm | 14.10 mm | 8.65 mm | 10.15 mm |
| Lag-8 persistence | 15.36 mm | 20.77 mm | 6.76 mm | 12.35 mm |

The forest reduced test RMSE and had higher test MAE. This sample does not show a consistent improvement over persistence.

| Classification | Macro precision | Macro recall | Macro F1 |
| --- | ---: | ---: | ---: |
| Validation | 0.1364 | 0.2500 | 0.1765 |
| Test | 0.1538 | 0.2500 | 0.1905 |

Training class counts were 8 No Rain, 107 Light Rain, 18 Moderate Rain, and 15 Heavy Rain. The classifier predicted Light Rain for every held-out day. The test confusion matrix was `[[0,15,0,0],[0,32,0,0],[0,4,0,0],[0,1,0,0]]`. Recall was zero for No Rain, Moderate Rain, and Heavy Rain. The tests verified persistence and inference behavior. The measured classifier does not distinguish intensity classes reliably on this sample.

## Testing

Run `python -m pytest` after installing `requirements-dev.txt` from each service directory. The database tests are opt-in with `FLOODINSIGHT_RUN_ML_DB_TESTS=1` on a disposable database named `floodinsight_ml_test`. Populate the benchmark dates above and the current seven eligible lag dates for Hải Châu via the historical warehouse API. Each suite checks that deleting its stored results and reissuing inference restores them from the same model. All nine ML service tests passed. All three trained models also served after their containers were recreated. The workspace export at `artifacts/ml-benchmark/` contains the three fitted Joblib files and a SHA-256-verified metrics manifest. These local benchmark files are ignored by Git. Deployment model volumes and registry entries are created through the training API.

