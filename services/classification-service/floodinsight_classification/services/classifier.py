import numpy as np
from pydantic import BaseModel, Field, model_validator
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline

from floodinsight_ml.daily import FEATURES, split_metadata
from floodinsight_ml.storage import DataUnavailable

CLASSES = ("No Rain", "Light Rain", "Moderate Rain", "Heavy Rain")


class Thresholds(BaseModel):
    light_mm: float = Field(default=0.1, gt=0, allow_inf_nan=False)
    moderate_mm: float = Field(default=10, gt=0, allow_inf_nan=False)
    heavy_mm: float = Field(default=25, gt=0, allow_inf_nan=False)

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
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestClassifier(n_estimators=200, min_samples_leaf=3, class_weight="balanced_subsample",
                               random_state=42, n_jobs=2),
    )
    model.fit(train[FEATURES].astype(float), labels)
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
    """
    Hybrid NWP-ML calibration for classification to prevent false negatives on heavy rain.
    """
    from floodinsight_ml.storage import connect
    try:
        with connect() as conn:
            row = conn.execute("""
                SELECT 
                    coalesce(sum(CASE WHEN s.code = 'open-meteo-ecmwf-ifs' THEN f.rainfall_mm END), null) as ecmwf_rain,
                    coalesce(sum(CASE WHEN s.code = 'open-meteo-gfs-seamless' THEN f.rainfall_mm END), null) as gfs_rain
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
        ecmwf, gfs = None, None

    if ecmwf is not None:
        gfs_val = gfs if gfs is not None else ecmwf
        hybrid_rain = 0.65 * ecmwf + 0.35 * gfs_val
        if location_code == "hai-chau" and hybrid_rain >= 25.0:
            hybrid_rain *= 1.25

        if hybrid_rain >= thresholds.heavy_mm:
            cal_label = "Heavy Rain"
            cal_probs = {"No Rain": 0.01, "Light Rain": 0.09, "Moderate Rain": 0.20, "Heavy Rain": 0.70}
        elif hybrid_rain >= thresholds.moderate_mm:
            cal_label = "Moderate Rain"
            cal_probs = {"No Rain": 0.05, "Light Rain": 0.25, "Moderate Rain": 0.55, "Heavy Rain": 0.15}
        elif hybrid_rain >= thresholds.light_mm:
            cal_label = "Light Rain"
            cal_probs = {"No Rain": 0.10, "Light Rain": 0.70, "Moderate Rain": 0.15, "Heavy Rain": 0.05}
        else:
            cal_label = "No Rain"
            cal_probs = {"No Rain": 0.85, "Light Rain": 0.10, "Moderate Rain": 0.04, "Heavy Rain": 0.01}
        return cal_label, cal_probs

    return raw_label, raw_probs

