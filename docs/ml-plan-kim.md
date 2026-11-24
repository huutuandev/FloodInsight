# ML implementation plan

## ml-common

- `daily.py`: loads ERA5 daily data and builds lag/availability-safe chronological training frames.
- `storage.py`: provides PostgreSQL connections, model artifact registry, and ML result persistence helpers.
- `schemas.py` / `api.py`: define shared request/window types and warehouse/model HTTP error handling.
- `daily_results.py`: persists and queries next-day prediction/classification results.
- Prediction uses these helpers for `training_partitions`, `inference_input`, `Models`, and `save_next_day`.

## Existing clustering and classification

- Clustering already provides KMeans, PCA, silhouette metrics, model/result persistence, and train/run/results/metrics endpoints.
- Classification already provides chronological split, RandomForest, macro F1/precision/recall, confusion matrix, probabilities, and train/predict/results/metrics endpoints.
- Keep existing implementations and data features; do not create a parallel proxy-label or feature pipeline.

## Docker and database

- Clustering and classification already match the prediction pattern:
  - `additional_contexts: ml_common` and `COPY --from=ml_common`.
  - dedicated model volumes and artifact directories.
  - `POSTGRES_*`, `POSTGRES_HOST`, and migration-complete dependencies.
  - pandas, NumPy, scikit-learn, joblib, psycopg, and Pydantic settings requirements.
- No new Docker, schema, or dependency change is needed before running the existing services.
