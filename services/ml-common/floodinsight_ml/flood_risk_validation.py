"""Evaluate scored operational exports without interpreting an unknown target."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

from .flood_features import VERSION
from .flood_risk import FACTORS, RiskConfig, assess, sensitivity


def evaluate(export, config):
    if export["mode"] != "operational" or export["schema"] != VERSION or "rows" not in export:
        raise ValueError("Backtests require a full operational export of the supported feature version")
    labels, confusion, categories = Counter(), Counter(), Counter()
    eligible, detected = set(), set()
    scored = abstained = 0
    for raw in export["rows"]:
        row = raw | {"issued_at": datetime.fromisoformat(raw["issued_at"]), "provenance": {
            feature: info | {"available_at": datetime.fromisoformat(info["available_at"])}
            for feature, info in raw["provenance"].items()
        }}
        risk = assess(row, config)
        categories[risk["risk_category"]] += 1
        label = row["label"]["status"]
        labels[label] += 1
        if label == "unknown":
            continue
        if risk["risk_index"] is None:
            abstained += 1
            continue
        scored += 1
        alert = risk["risk_category"] in ("High", "Very High")
        positives = row["label"]["event_keys"] if label == "positive" else []
        eligible.update(positives)
        if alert:
            detected.update(positives)
        confusion[(label, alert)] += 1
    tp, fn = confusion["positive", True], confusion["positive", False]
    fp, tn = confusion["negative", True], confusion["negative", False]
    return {
        "rows": len(export["rows"]), "label_counts": {key: labels[key] for key in ("positive", "negative", "unknown")},
        "settings": export.get("settings"), "label_as_of": export.get("label_as_of"),
        "rows_sha256": export.get("rows_sha256"),
        "risk_categories": dict(categories), "labeled_scored": scored, "labeled_abstained": abstained,
        "confusion_scored_only": {"tp": tp, "fp": fp, "tn": tn, "fn": fn} if scored else None,
        "sensitivity_scored_only": tp / (tp + fn) if tp + fn else None,
        "specificity_scored_only": tn / (tn + fp) if tn + fp else None,
        "precision_scored_only": tp / (tp + fp) if tp + fp else None,
        "scoreable_positive_event_keys": len(eligible),
        "detected_event_keys": len(detected) if eligible else None,
        "validation_status": "scored_labeled_rows_exploratory" if scored else "not_evaluable",
    }


def illustrative_sensitivity(config):
    # Mathematical probes for parameter sensitivity, never joined to the warehouse.
    scenarios = {
        "lower_rain": (10, 15, 10, 12, .45, .25),
        "near_boundary": (45, 54, 23, 10, .63, .35),
        "large_rain": (105, 90, 45, 5, .90, .48),
    }
    keys = [key for factor in FACTORS.values() for key in factor]
    issue = datetime.fromisoformat("2020-01-01T00:00:00+00:00")
    return {name: sensitivity({
        "mode": "operational", "location": "illustrative", "latitude": 0.0, "longitude": 0.0,
        "issued_at": issue, "features": dict(zip(keys, values)), "weather_bins": [],
        "provenance": {key: {"available_at": issue, "source_ids": []} for key in keys},
    }, config) for name, values in scenarios.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", nargs="?", help="Operational export path or - for stdin")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config = RiskConfig.model_validate_json(args.config.read_text(encoding="utf-8")) if args.config else RiskConfig()
    result = {"illustrative_sensitivity": illustrative_sensitivity(config)}
    if args.export:
        raw = (sys.stdin.buffer.read().decode("utf-8-sig") if args.export == "-" else
               Path(args.export).read_text(encoding="utf-8-sig"))
        result["backtest"] = evaluate(json.loads(raw), config)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
