import numpy as np
from pydantic import BaseModel, Field, model_validator
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from xgboost import XGBClassifier

from floodinsight_ml.daily import FEATURES, split_metadata
from floodinsight_ml.storage import DataUnavailable, connect

CLASSES = ("No Rain", "Light Rain", "Moderate Rain", "Heavy Rain")


class Thresholds(BaseModel):
    light_mm: float = Field(default=0.1, gt=0, allow_inf_nan=False)
    moderate_mm: float = Field(default=15.0, gt=0, allow_inf_nan=False)
    heavy_mm: float = Field(default=50.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if not self.light_mm < self.moderate_mm < self.heavy_mm:
            raise ValueError("Require light_mm < moderate_mm < heavy_mm")
        return self


def rainfall_labels(values, thresholds: Thresholds):
    return np.digitize(np.asarray(values), [thresholds.light_mm, thresholds.moderate_mm, thresholds.heavy_mm])


def classification_metrics(actual, predicted):
    labels = list(range(len(CLASSES)))
    p, r, f, support = precision_recall_fscore_support(
        actual, predicted, labels=labels, zero_division=0,
    )
    return {
        "precision_macro": float(np.mean(p)), "recall_macro": float(np.mean(r)),
        "f1_macro": float(np.mean(f)),
        "per_class": {
            label: {"precision": float(p[i]), "recall": float(r[i]),
                    "f1": float(f[i]), "support": int(support[i])}
            for i, label in enumerate(CLASSES)
        },
        "confusion_matrix": confusion_matrix(actual, predicted, labels=labels).tolist(),
    }


def train_classifier(parts, thresholds):
    train = parts["train"]
    labels = rainfall_labels(train["target"], thresholds)
    training_counts = np.bincount(labels, minlength=len(CLASSES))
    if (training_counts == 0).any():
        raise DataUnavailable("The training partition must contain all four configured rainfall classes")
    n_total = len(labels)
    n_classes = len(CLASSES)
    class_weights = {i: n_total / (n_classes * max(training_counts[i], 1)) for i in range(n_classes)}
    sample_weights = np.array([class_weights[lbl] for lbl in labels])
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        XGBClassifier(
            n_estimators=600,
            learning_rate=0.04,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            reg_alpha=0.05,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=2,
            tree_method="hist",
            eval_metric="mlogloss",
        ),
    )
    model.fit(train[FEATURES].astype(float), labels, xgbclassifier__sample_weight=sample_weights)
    metrics = {}
    for name in ("validation", "test"):
        rows = parts[name]
        metrics[name] = classification_metrics(
            rainfall_labels(rows["target"], thresholds), model.predict(rows[FEATURES].astype(float)),
        )
    splits = split_metadata(parts)
    splits["train"]["class_counts"] = dict(zip(CLASSES, training_counts.tolist()))
    return model, splits, metrics


def predict_class(model, features):
    values = model.predict_proba(features)[0]
    by_code = {int(code): float(value) for code, value in zip(model.classes_, values)}
    probabilities = {name: by_code.get(i, 0.0) for i, name in enumerate(CLASSES)}
    return max(probabilities, key=probabilities.__getitem__), probabilities


def calibrate_classification(location_code: str, target_date, raw_label: str, raw_probs: dict, thresholds: Thresholds):
    """Align classification with predicted rainfall & live NWP so class labels 100% match rainfall mm."""
    pred_rain, live_rain, ecmwf, gfs = None, None, None, None
    try:
        with connect() as conn:
            pred_row = conn.execute("""
                SELECT r.rainfall_mm::float8 AS rain_mm
                FROM prediction_results r
                JOIN dim_location l ON l.id = r.location_id
                JOIN dim_time t ON t.hour_start_utc = r.target_hour_utc
                WHERE l.code = %s AND t.local_date = %s
                ORDER BY r.issued_at DESC LIMIT 1
            """, (location_code, target_date)).fetchone()
            if pred_row and pred_row.get("rain_mm") is not None:
                pred_rain = float(pred_row["rain_mm"])

            live_row = conn.execute("""
                WITH latest_hourly AS (
                    SELECT DISTINCT ON (r.valid_at)
                           GREATEST(
                               COALESCE(CASE WHEN jsonb_typeof(r.payload->'values'->'precipitation') = 'number'
                                    THEN (r.payload->'values'->>'precipitation')::float8 END, 0.0),
                               COALESCE(CASE WHEN jsonb_typeof(r.payload->'values'->'rain') = 'number'
                                    THEN (r.payload->'values'->>'rain')::float8 END, 0.0)
                           ) AS rain_mm
                    FROM raw_weather_forecasts r
                    JOIN data_sources d ON d.id = r.source_id
                    WHERE d.code = 'open-meteo-forecast-api'
                      AND r.source_location_key = %s
                      AND r.payload->>'kind' = 'hourly'
                      AND r.valid_at > warehouse_local_day_start(%s)
                      AND r.valid_at <= warehouse_local_day_start(%s::date + 1)
                    ORDER BY r.valid_at, r.received_at DESC, r.id DESC
                )
                SELECT sum(rain_mm)::float8 AS total_rain, count(*) AS hrs FROM latest_hourly
            """, (location_code, target_date, target_date)).fetchone()
            if live_row and live_row.get("total_rain") is not None and int(live_row.get("hrs") or 0) >= 12:
                live_rain = float(live_row["total_rain"])

            row = conn.execute("""
                SELECT
                    coalesce(sum(CASE WHEN s.code = 'open-meteo-ecmwf-ifs' THEN f.rainfall_mm END), null) AS ecmwf_rain,
                    coalesce(sum(CASE WHEN s.code = 'open-meteo-gfs-seamless' THEN f.rainfall_mm END), null) AS gfs_rain
                FROM fact_weather_forecast_hourly f
                JOIN dim_time t USING (hour_start_utc)
                JOIN dim_location l ON l.id = f.location_id
                JOIN dim_weather_source ws ON ws.id = f.weather_source_id
                JOIN data_sources s ON s.id = ws.data_source_id
                WHERE l.code = %s AND t.local_date = %s
            """, (location_code, target_date)).fetchone()
            ecmwf = float(row["ecmwf_rain"]) if row and row.get("ecmwf_rain") is not None else None
            gfs = float(row["gfs_rain"]) if row and row.get("gfs_rain") is not None else None
    except Exception:
        pass

    reference_rain = pred_rain
    if reference_rain is None:
        primary_nwp = live_rain if live_rain is not None else ecmwf
        if primary_nwp is not None:
            secondary_nwp = ecmwf if (live_rain is not None and ecmwf is not None) else (gfs if gfs is not None else primary_nwp)
            reference_rain = 0.70 * primary_nwp + 0.30 * secondary_nwp

    if reference_rain is not None:
        if reference_rain >= thresholds.heavy_mm:
            target_cls = "Heavy Rain"
            nwp_prior = {"No Rain": 0.01, "Light Rain": 0.05, "Moderate Rain": 0.19, "Heavy Rain": 0.75}
        elif reference_rain >= thresholds.moderate_mm:
            target_cls = "Moderate Rain"
            nwp_prior = {"No Rain": 0.02, "Light Rain": 0.18, "Moderate Rain": 0.68, "Heavy Rain": 0.12}
        elif reference_rain >= thresholds.light_mm:
            target_cls = "Light Rain"
            nwp_prior = {"No Rain": 0.08, "Light Rain": 0.74, "Moderate Rain": 0.15, "Heavy Rain": 0.03}
        else:
            target_cls = "No Rain"
            nwp_prior = {"No Rain": 0.88, "Light Rain": 0.09, "Moderate Rain": 0.02, "Heavy Rain": 0.01}

        blended = {
            cls: round(0.70 * nwp_prior[cls] + 0.30 * float(raw_probs.get(cls, 0.0)), 4)
            for cls in CLASSES
        }
        total = sum(blended.values()) or 1.0
        normalized = {cls: round(val / total, 4) for cls, val in blended.items()}
        return target_cls, normalized

    return raw_label, raw_probs

