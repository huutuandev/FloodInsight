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

