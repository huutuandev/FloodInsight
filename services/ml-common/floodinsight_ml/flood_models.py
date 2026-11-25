"""Flood candidate fitting, independent calibration and locked evaluation."""

from collections import defaultdict
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, balanced_accuracy_score, brier_score_loss, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .flood_training_data import FEATURES, event_groups, support, weather_grids

POLICY_VERSION = "flood-release-screen-v1"
RAINFALL_BASELINE_MM = 100
MISS_COST = 5
ISOTONIC_MIN_ROWS = 1000


def matrix(rows):
    return np.asarray([[row["features"][name] for name in FEATURES] for row in rows], dtype=float)


def outcomes(rows):
    return np.asarray([row["label"]["value"] for row in rows], dtype=int)


def candidates():
    return {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000)),
        "random_forest": RandomForestClassifier(n_estimators=200, min_samples_leaf=10, n_jobs=2,
                                               class_weight="balanced_subsample", random_state=42),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=150, early_stopping=False,
                                                                 class_weight="balanced", random_state=42),
    }


def logit(prob):
    prob = np.clip(prob, 1e-6, 1 - 1e-6)
    return np.log(prob / (1 - prob)).reshape(-1, 1)


def probabilities(artifact, inputs):
    raw = artifact["estimator"].predict_proba(inputs)[:, 1]
    if artifact["calibration"] == "sigmoid":
        return artifact["calibrator"].predict_proba(logit(raw))[:, 1]
    if artifact["calibration"] == "isotonic":
        return artifact["calibrator"].predict(raw)
    raise ValueError("Unrecognized calibration method")


def event_results(rows, decision):
    groups = event_groups(rows)
    detected = {groups[key] for row, alert in zip(rows, decision) if alert and row["label"]["status"] == "positive"
                for key in row["label"]["event_keys"]}
    count = len(set(groups.values()))
    return {"episodes": count, "detected": len(detected), "missed": count - len(detected),
            "missed_rate": (count - len(detected)) / count if count else None}


def decision_cost(rows, decision):
    false_alarms = np.count_nonzero(decision & (outcomes(rows) == 0))
    return int(false_alarms) + MISS_COST * event_results(rows, decision)["missed"]


def choose_threshold(rows, probability):
    # Tie-break towards the higher threshold when estimated costs are equal.
    return min(np.linspace(0, 1, 101), key=lambda threshold: (decision_cost(rows, probability >= threshold), -threshold))


def reliability(actual, probability):
    bins = np.minimum((probability * 10).astype(int), 9)
    return [{"left": i / 10, "right": (i + 1) / 10, "count": int(sum(bins == i)),
             "mean_probability": float(np.mean(probability[bins == i])),
             "positive_fraction": float(np.mean(actual[bins == i]))}
            for i in range(10) if np.any(bins == i)]


def metrics(rows, probability, decision):
    y = outcomes(rows)
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y, decision, labels=[0, 1]).ravel())
    mixed = len(set(y)) == 2
    return {
        "positive": tp + fn, "negative": tn + fp,
        "accuracy": float(accuracy_score(y, decision)),
        "balanced_accuracy": float(balanced_accuracy_score(y, decision)) if mixed else None,
        "precision": float(precision_score(y, decision)) if tp + fp else None,
        "recall": float(recall_score(y, decision)) if tp + fn else None,
        "f1": float(f1_score(y, decision)) if 2 * tp + fp + fn else None,
        "pr_auc_average_precision": float(average_precision_score(y, probability)) if mixed else None,
        "roc_auc": float(roc_auc_score(y, probability)) if mixed else None,
        "brier": float(brier_score_loss(y, probability)),
        "calibration_curve": reliability(y, probability),
        "confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "false_alarm_rate": fp / (tn + fp) if tn + fp else None,
        "missed_positive_row_rate": fn / (tp + fn) if tp + fn else None,
        "event_performance": event_results(rows, decision),
        "decision_cost": decision_cost(rows, decision),
        "uncertainty_intervals": None,
        "interval_limitation": "Temporal event grouping alone does not establish independent storm and dry sampling blocks",
    }


def development(parts):
    fit, cal, selection = (parts[role] for role in ("fit", "calibration", "selection"))
    x_fit, x_cal, x_selection = matrix(fit), matrix(cal), matrix(selection)
    y_fit, y_cal, y_selection = outcomes(fit), outcomes(cal), outcomes(selection)
    comparisons, scored = [], []
    for name, estimator in candidates().items():
        estimator.fit(x_fit, y_fit)
        raw_cal = estimator.predict_proba(x_cal)[:, 1]
        raw_selection = estimator.predict_proba(x_selection)[:, 1]
        raw_brier = float(brier_score_loss(y_selection, raw_selection))
        sigmoid = LogisticRegression().fit(logit(raw_cal), y_cal)
        calibrators = {"sigmoid": sigmoid} if sigmoid.coef_[0, 0] > 0 else {}
        if (len(cal) >= ISOTONIC_MIN_ROWS and np.unique(raw_cal).size >= 10
                and min(np.bincount(y_cal, minlength=2)) >= 50):
            calibrators["isotonic"] = IsotonicRegression(out_of_bounds="clip").fit(raw_cal, y_cal)
        for method in ("sigmoid", "isotonic"):
            if method not in calibrators:
                comparisons.append({"candidate": name, "method": method, "raw_selection_brier": raw_brier,
                                    "status": "nonmonotonic_fit" if method == "sigmoid" else "insufficient_calibration_support"})
                continue
            artifact = {"estimator": estimator, "calibrator": calibrators[method], "calibration": method}
            estimates = probabilities(artifact, x_selection)
            threshold = float(choose_threshold(selection, estimates))
            evaluation = metrics(selection, estimates, estimates >= threshold)
            comparisons.append({"candidate": name, "method": method, "threshold": threshold,
                                "raw_selection_brier": raw_brier, "calibrated_selection": evaluation})
            if evaluation["brier"] < raw_brier:
                scored.append((evaluation["brier"], evaluation["decision_cost"], name, method,
                               threshold, artifact))
    if not scored:
        return None, {"status": "validation_failed", "reason": "No calibration improved selection-set Brier",
                      "policy_version": POLICY_VERSION, "candidates": comparisons}
    _, _, name, method, threshold, artifact = min(scored, key=lambda item: item[:4])
    importance = permutation_importance(artifact["estimator"], x_selection, y_selection,
                                        scoring="neg_brier_score", n_repeats=5, random_state=42)

    # The candidate and all decision rules are locked before this first use of test features.
    test = parts["test"]
    x_test = matrix(test)
    estimated = probabilities(artifact, x_test)
    decisions = estimated >= threshold
    observed = outcomes(test)
    assessment = metrics(test, estimated, decisions)
    raw_brier = float(brier_score_loss(observed, artifact["estimator"].predict_proba(x_test)[:, 1]))
    prior = float((sum(y_fit) + 1) / (len(y_fit) + 2))
    prior_score = np.full(len(test), prior)
    prior_threshold = choose_threshold(selection, np.full(len(selection), prior))
    rain = x_test[:, FEATURES.index("forecast_rain_next_24h_mm")] >= RAINFALL_BASELINE_MM
    baselines = {
        "historical_frequency": metrics(test, prior_score, prior_score >= prior_threshold),
        "rainfall_threshold_mm_100_hard_baseline": metrics(test, rain.astype(float), rain),
    }
    location_indices = defaultdict(list)
    for i, row in enumerate(test):
        location_indices[row["location"]].append(i)
    per_location, validated = {}, {}
    for location, indices in sorted(location_indices.items()):
        subset = [test[i] for i in indices]
        coverage = support(subset)
        local = metrics(subset, estimated[indices], decisions[indices])
        local_baseline = metrics(subset, prior_score[indices], prior_score[indices] >= prior_threshold)
        local_rain_cost = decision_cost(subset, rain[indices])
        local_raw_brier = float(brier_score_loss(outcomes(subset),
                                                artifact["estimator"].predict_proba(x_test[indices])[:, 1]))
        per_location[location] = {"coverage": coverage, "metrics": local, "frequency_baseline": local_baseline,
                                  "raw_brier": local_raw_brier, "rain_baseline_cost": local_rain_cost}
        if (coverage["independent_event_candidates"] >= 5 and coverage["distinct_dry_utc_days"] >= 20
                and local["brier"] < min(local_baseline["brier"], local_raw_brier)
                and local["decision_cost"] <= min(local_rain_cost, local_baseline["decision_cost"])
                and local["event_performance"]["detected"] > 0):
            values = x_test[indices]
            validated[location] = {
                "weather_grids": [list(g) for g in sorted({g for row in subset for g in weather_grids(row)})],
                "feature_range": dict(zip(FEATURES, zip(values.min(axis=0).tolist(), values.max(axis=0).tolist()))),
            }
    passes = (assessment["brier"] < min(baselines["historical_frequency"]["brier"], raw_brier)
              and assessment["decision_cost"] <= min(baseline["decision_cost"] for baseline in baselines.values())
              and assessment["event_performance"]["detected"] > 0 and bool(validated))
    report = {
        "status": "eligible_for_release_review" if passes else "validation_failed",
        "policy_version": POLICY_VERSION, "candidates": comparisons, "winner": name, "calibration": method,
        "threshold": threshold, "test": assessment, "test_raw_brier": raw_brier,
        "frequency_fit_prior": prior, "frequency_threshold": float(prior_threshold),
        "test_baselines": baselines, "test_by_location": per_location, "validated_locations": validated,
        "feature_importance": dict(zip(FEATURES, importance.importances_mean.tolist())),
    }
    if passes:
        artifact["reference"] = np.median(x_fit, axis=0)
    return (artifact if passes else None), report
