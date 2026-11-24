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

Random forest regression compares MAE and RMSE with a persistence baseline using the most recent eligible rain lag, day minus 8. Classification uses a separate random forest with balanced subsampling weights. The default classes are project-defined daily intensity categories:

| Class | Daily rainfall |
| --- | --- |
| No Rain | Less than 0.1 mm, including trace amounts |
| Light Rain | 0.1 to less than 10 mm |
| Moderate Rain | 10 to less than 25 mm |
| Heavy Rain | 25 mm or more |

Configure the lower boundaries as `thresholds.light_mm`, `thresholds.moderate_mm`, and `thresholds.heavy_mm` when training. All four classes must occur in the training split. Confusion matrices use the class order above, with actual class on rows and predicted class on columns. Returned probabilities are random forest class estimates. Flood forecasting would require reliable flood-event labels and a separate evaluation.

## Measured evaluation

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

## 2024-2025 retrospective retrain

This run used Hải Châu, retrospective availability, and 2024-01-01 through 2025-12-31. The monthly climatology baseline was fitted only on training targets and predicts the mean target rainfall for that calendar month, with the train mean fallback for unseen months.

| Regression | Validation MAE | Validation RMSE | Test MAE | Test RMSE |
| --- | ---: | ---: | ---: | ---: |
| Random forest | 6.037363 mm | 17.564344 mm | 13.181860 mm | 20.021191 mm |
| Lag-8 persistence | 8.057778 mm | 24.909186 mm | 19.400000 mm | 28.687889 mm |
| Monthly climatology | 4.888148 mm | 17.193459 mm | 13.924185 mm | 20.595251 mm |

On validation, climatology had the lowest MAE and RMSE. On test, the random forest had the lowest MAE and RMSE, while lag-8 was worse on both metrics. This run shows that the model improved on the two baselines on test data, but climatology remained close to the model and was slightly better on validation.

## Pooled 9-location retrospective retrain

The pooled model omitted `location`, training 2024-01-01 through 2025-12-31 across Hải Châu, Thanh Khê, Liên Chiểu, Cẩm Lệ, Ngũ Hành Sơn, Sơn Trà, Hòa Vang, Hòa Bắc, and Hòa Khương with retrospective availability. All nine locations have ERA5 archive coverage from 2024-01-01 through 2026-11-18. The 2022-10-14 VRAIN ground-gauge peak is outside this training window and was not included in either the chronological train, validation, or test partitions.

| Regression | Validation MAE | Validation RMSE | Test MAE | Test RMSE |
| --- | ---: | ---: | ---: | ---: |
| Random forest | 7.274157 mm | 18.635214 mm | 14.691558 mm | 23.590159 mm |
| Lag-8 persistence | 8.822305 mm | 25.762162 mm | 19.909336 mm | 30.177952 mm |
| Monthly climatology | 5.691407 mm | 17.836064 mm | 14.330004 mm | 21.818623 mm |

The pooled test split had 1,296 samples; climatology was close to the random forest and had 0.361554 mm lower test MAE, while the random forest had 1.770336 mm lower test RMSE. The random forest outperformed lag-8 on test MAE and RMSE. On validation, climatology had the lowest MAE and RMSE.

## Pooled residual and simple-tree experiments

Three pooled 9-location cases used 2024-01-01 through 2025-12-31 with retrospective availability. Residual targets were real rainfall minus train-fitted monthly climatology, and residual predictions were clipped to zero. The simple residual forest used `max_depth=5` and `min_samples_leaf=10`; parameters were compared on validation only.

| Case | Validation MAE | Validation RMSE | Test MAE | Test RMSE |
| --- | ---: | ---: | ---: | ---: |
| Default Random Forest | 7.274157 mm | 18.635214 mm | 14.691558 mm | 23.590159 mm |
| Residual on climatology | 6.440924 mm | 18.190725 mm | 14.243024 mm | 23.456535 mm |
| Residual + simple tree | 5.714837 mm | 17.914736 mm | 14.925594 mm | 22.889526 mm |
| Lag-8 persistence | 8.822305 mm | 25.762162 mm | 19.909336 mm | 30.177952 mm |
| Monthly climatology | 5.691407 mm | 17.836064 mm | 14.330004 mm | 21.818623 mm |

The residual + simple tree was the best validation model among the three ML cases, but it did not beat monthly climatology; climatology had 0.023430 mm lower validation MAE and 0.078672 mm lower validation RMSE. No alternative beat climatology on validation. The test values are reported for completeness and were not used for parameter selection.

| Classification | Macro precision | Macro recall | Macro F1 |
| --- | ---: | ---: | ---: |
| Validation | 0.1364 | 0.2500 | 0.1765 |
| Test | 0.1538 | 0.2500 | 0.1905 |

Training class counts were 8 No Rain, 107 Light Rain, 18 Moderate Rain, and 15 Heavy Rain. The classifier predicted Light Rain for every held-out day. The test confusion matrix was `[[0,15,0,0],[0,32,0,0],[0,4,0,0],[0,1,0,0]]`. Recall was zero for No Rain, Moderate Rain, and Heavy Rain. The tests verified persistence and inference behavior. The measured classifier does not distinguish intensity classes reliably on this sample.

## Thử nghiệm ngưỡng KTTV và cân bằng lớp

This is an experiment only. The 0.1/10/25 mm project thresholds remain the defaults. The existing production behavior uses Random Forest `balanced_subsample`; the API now accepts `class_weight="balanced"` explicitly. Every run below uses the retrospective availability mode for 2024-01-01 through 2025-12-31.

| Case | Thresholds (No Rain / Light / Moderate / Heavy) | Accuracy | Macro F1 | No Rain recall | Light recall | Moderate recall | Heavy recall | Majority baseline |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Default thresholds, balanced_subsample | 0.1 / 10 / 25 mm | 56.25% | 0.383435 | 0.500000 | 0.804598 | 0.068966 | 0.272727 | 60.42% |
| Default thresholds, balanced | 0.1 / 10 / 25 mm | 54.17% | 0.399863 | 0.500000 | 0.735632 | 0.137931 | 0.318182 | 60.42% |
| KTTV thresholds, balanced_subsample | 0.1 / 16 / 50 mm | 61.81% | 0.256067 | 0.166667 | 0.877551 | 0.068966 | 0.000000 | 68.06% |
| KTTV thresholds, balanced | 0.1 / 16 / 50 mm | 60.42% | 0.301231 | 0.333333 | 0.816327 | 0.172414 | 0.000000 | 68.06% |

The 2024-2025 training class counts were:

| Case thresholds | No Rain | Light Rain | Moderate Rain | Heavy Rain |
| --- | ---: | ---: | ---: | ---: |
| 0.1 / 10 / 25 mm | 455 | 1245 | 265 | 145 |
| 0.1 / 16 / 50 mm | 455 | 1370 | 245 | 40 |

Sources for the experimental thresholds: the National Centre for Hydro-Meteorological Forecasting WMO rain classification (moderate rain 16-50 mm/24h, heavy rain >50 mm/24h) and the Daibieunhandan.vn article "Hỏi - đáp về các hiện tượng khí tượng thủy văn". The KTTV grouping was used only in training/evaluation and does not change the documented project defaults.

## Thử nghiệm gộp 3 lớp

The optional `three_classes=true` mode uses fixed boundaries: No Rain `<0.1 mm`, Light Rain `0.1` to `<16 mm`, and Moderate+ `>=16 mm`; it is disabled by default and does not change the 4-class thresholds. Both runs used Hải Châu, retrospective availability, and 2024-01-01 through 2025-12-31. The test split below has 144 samples.

| Case | Accuracy | Macro F1 | No Rain recall | Light recall | Moderate+ recall | Train counts (No/Light/Moderate+) | Majority baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| balanced_subsample | 63.89% | 0.520290 | 33.33% (6) | 74.49% (98) | 42.50% (40) | 91 / 274 / 57 | 68.06% |
| balanced | 52.08% | 0.436456 | 33.33% (6) | 48.98% (98) | 62.50% (40) | 91 / 274 / 57 | 68.06% |

`balanced_subsample` was better on test accuracy and macro F1 in this run, but both models remained below the 68.06% majority baseline. `balanced` improved Moderate+ recall at the cost of Light Rain recall and accuracy. These 3-class results are experimental; the default API remains 4 classes.

## Thử nghiệm quét cụm k

The clustering API keeps `clusters=3` as its default and accepts `scan_k=true` to evaluate `k=2..6`. For the 2024-01-01 through 2025-12-31 Hải Châu window, 731 complete samples were used.

| k | Silhouette |
| ---: | ---: |
| 2 | 0.370919 |
| 3 | 0.298500 |
| 4 | 0.295438 |
| 5 | 0.282499 |
| 6 | 0.276925 |

The best result was `k=2`. Its cluster means were:

| Cluster | Days | Rainfall (mm) | Rain intensity (mm/h) | Rainy hours | Humidity (%) | Temperature (C) | Wind (m/s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 537 | 2.277 | 0.276 | 5.559 | 80.712 | 27.653 | 2.250 |
| 1 | 194 | 23.201 | 1.044 | 21.933 | 87.083 | 24.360 | 3.780 |

Cluster 1 represents wetter, more humid, and rainier periods; Cluster 0 represents predominantly dry/light-rain periods. The scan does not change the default `k=3`.

## Giới hạn đặc trưng

Supervised features start at target day minus 8 (`D-8`) to enforce the data availability/embargo design. Consequently, classification and prediction mainly learn from lagged rainfall and weather patterns plus seasonality, not the latest 1-3 recorded days. This limits next-day forecasting to evidence available before D-7 and makes seasonal persistence a major competing signal; adding D-1 to D-3 is not implemented here.

## Testing

Run `python -m pytest` after installing `requirements-dev.txt` from each service directory. The database tests are opt-in with `FLOODINSIGHT_RUN_ML_DB_TESTS=1` on a disposable database named `floodinsight_ml_test`. Populate the benchmark dates above and the current seven eligible lag dates for Hải Châu via the historical warehouse API. Each suite checks that deleting its stored results and reissuing inference restores them from the same model. All nine ML service tests passed. All three trained models also served after their containers were recreated. The workspace export at `artifacts/ml-benchmark/` contains the three fitted Joblib files and a SHA-256-verified metrics manifest. These local benchmark files are ignored by Git. Deployment model volumes and registry entries are created through the training API.

