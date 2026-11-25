"""Versioned point-level flood predictors and conservative 24-hour targets."""

from collections import defaultdict
from datetime import timedelta
import math

from .availability import ERA5_DELAY, archive_available_at

VERSION = "flood-point-v1"
HOUR = timedelta(hours=1)
TARGET = 24 * HOUR
RADIUS_M = 50
WET_MM = 0.1
LOOKBACKS = (1, 3, 6, 12, 24, 48, 72)
FORECASTS = (6, 12, 24)
SCHEMA = (
    {f"rain_prev_{h}h_mm": "mm" for h in LOOKBACKS}
    | {
        "rain_max_hour_prev_24h_mm": "mm", "rain_max_3h_prev_24h_mm": "mm",
        "wet_hour_intensity_prev_24h_mm_per_h": "mm/h", "wet_hours_prev_24h": "h",
        "longest_wet_spell_prev_24h": "h", "antecedent_rain_delayed_24h_mm": "mm",
        "antecedent_rain_delayed_72h_mm": "mm",
    }
    | {f"forecast_rain_next_{h}h_mm": "mm" for h in FORECASTS}
    | {
        "soil_moisture_delayed": "m³/m³", "elevation_m": "m", "surface_slope_deg": "degree",
        "land_cover_class": "class_code", "built_up_fraction": "fraction",
        "offshore_sea_level_msl_m": "m", "reported_flood_events_prev_365d": "count",
    }
)
TERRAIN = {
    ("elevation", "m"): "elevation_m",
    ("surface_slope", "degree"): "surface_slope_deg",
    ("worldcover_class", "class_code"): "land_cover_class",
    ("worldcover_built_up_fraction_11x11", "fraction"): "built_up_fraction",
}


def measurement(value, low=0, high=math.inf):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        return None
    return value


def grid(row):
    coords = row["grid"]
    if not isinstance(coords, dict):
        return None
    latitude = measurement(coords.get("latitude"), -90, 90)
    longitude = measurement(coords.get("longitude"), -180, 180)
    return (row["source"], latitude, longitude) if latitude is not None and longitude is not None else None


def window(series, start, hours):
    rows = [series.get(start + offset * HOUR) for offset in range(hours)]
    if any(row is None for row in rows):
        return None
    return rows


def distance_metres(point, obs):
    lat, lon = (math.radians(float(point[key])) for key in ("latitude", "longitude"))
    other_lat, other_lon = (math.radians(float(obs[key])) for key in ("latitude", "longitude"))
    term = math.sin((other_lat - lat) / 2) ** 2 + (
        math.cos(lat) * math.cos(other_lat) * math.sin((other_lon - lon) / 2) ** 2
    )
    return 2 * 6371008.8 * math.asin(math.sqrt(min(1, term)))


def assessed(point, observations, as_of):
    for obs in observations:
        if (obs["location_id"] != point["id"] or obs["quality"] not in ("high", "medium")
                or obs["observed_at"] > as_of or obs["available_at"] > as_of):
            continue
        distance = distance_metres(point, obs)
        uncertainty = obs["spatial_uncertainty_m"]
        if (obs["label"] == "flood_confirmed" and distance + uncertainty <= RADIUS_M
                and obs["event_key"] and obs["event_start"] <= obs["observed_at"] < obs["event_end"]):
            yield obs
        if (obs["label"] == "non_flood_confirmed" and obs["coverage_evidence"]
                and obs["coverage_radius_m"] is not None
                and obs["coverage_radius_m"] >= distance + uncertainty + RADIUS_M):
            yield obs


def target(point, observations, issuance, as_of):
    end = issuance + TARGET
    if end > as_of:
        return {"value": None, "status": "unknown", "reason": "horizon_open", "event_keys": []}
    positives, negatives = [], []
    for row in assessed(point, observations, as_of):
        if row["label"] == "flood_confirmed" and issuance < row["observed_at"] <= end:
            positives.append(row)
        if (row["label"] == "non_flood_confirmed" and row["coverage_start"] <= issuance
                and row["coverage_end"] >= end):
            negatives.append(row)
    event_keys = sorted({row["event_key"] for row in positives})
    if bool(positives) == bool(negatives):
        return {"value": None, "status": "unknown", "reason": "conflicting_evidence" if positives else
                "no_qualifying_coverage", "event_keys": event_keys}
    evidence = positives or negatives
    return {
        "value": int(bool(positives)), "status": "positive" if positives else "negative",
        "confidence": "high" if any(row["quality"] == "high" for row in evidence) else "medium",
        "available_at": max(end, min(row["available_at"] for row in evidence)),
        "observation_ids": sorted(row["id"] for row in evidence), "event_keys": event_keys,
        "event_windows": sorted({(row["event_start"], row["event_end"]) for row in positives}),
    }


def longest_wet_run(values):
    current = best = 0
    for value in values:
        current = current + 1 if value >= WET_MM else 0
        best = max(current, best)
    return best


def validate_holdout(training, evaluation, grid_groups):
    """Reject temporal overlap and shared rainfall grids in an independent holdout."""
    if not training or not evaluation:
        raise ValueError("Both splits need independently reviewed labeled rows")
    first_issue = min(row["issued_at"] for row in evaluation)
    for row in (*training, *evaluation):
        if row["mode"] != "operational":
            raise ValueError("Independent operational holdout requires recorded receipt mode")
        if row["label"]["status"] not in ("positive", "negative"):
            raise ValueError("Unknown or disputed targets cannot enter a supervised split")
    if any(max(row["target_end"], row["label"]["available_at"]) >= first_issue for row in training):
        raise ValueError("Training targets or their evidence overlap the evaluation issuance")
    left = {row["location"] for row in training}
    right = {row["location"] for row in evaluation}
    if left & right or any(left.intersection(group) and right.intersection(group) for group in grid_groups):
        raise ValueError("Holdout shares a point or rainfall-grid group")
    train_events = {key for row in training for key in row["label"]["event_keys"]}
    if any(train_events.intersection(row["label"]["event_keys"]) for row in evaluation):
        raise ValueError("Holdout shares a documented flood event")
    left_spans = {span for row in training for span in row["label"].get("event_windows", [])}
    right_spans = {span for row in evaluation for span in row["label"].get("event_windows", [])}
    if any(start < other_end and other_start < end for start, end in left_spans
           for other_start, other_end in right_spans):
        raise ValueError("Holdout spans overlap a documented flood episode")


def make_row(point, issuance, as_of, mode, inputs, *, include_validity=False):
    features = dict.fromkeys(SCHEMA)
    provenance = {}
    weather_bins = set()

    def put(name, value, rows):
        features[name] = value
        if value is not None:
            provenance[name] = {
                "source_ids": sorted({(row["source"], row["id"]) for row in rows}),
                "available_at": max(row["available_at"] for row in rows),
            }
            if include_validity:
                valid = [row["hour"] + HOUR if "hour" in row else row.get("valid_at", row.get("observed_at"))
                         for row in rows]
                valid = [instant for instant in valid if instant is not None]
                provenance[name]["first_valid_at"] = min(valid, default=None)
                provenance[name]["last_valid_at"] = max(valid, default=None)
            for row in rows:
                if row.get("weather_bin"):
                    weather_bins.add(row["weather_bin"])

    history = {}
    for row in inputs["rain"]:
        available = archive_available_at(row["hour"] + HOUR, row["received_at"], mode)
        if available is not None and available <= issuance and measurement(row["rain"]) is not None:
            history[row["hour"]] = row | {"available_at": available}
    for hours in LOOKBACKS:
        rows = window(history, issuance - hours * HOUR, hours)
        if rows:
            put(f"rain_prev_{hours}h_mm", math.fsum(row["rain"] for row in rows), rows)
    rows = window(history, issuance - TARGET, 24)
    if rows:
        rain = [row["rain"] for row in rows]
        wet = [value for value in rain if value >= WET_MM]
        put("rain_max_hour_prev_24h_mm", max(rain), rows)
        put("rain_max_3h_prev_24h_mm", max(math.fsum(rain[i:i + 3]) for i in range(22)), rows)
        put("wet_hours_prev_24h", len(wet), rows)
        put("longest_wet_spell_prev_24h", longest_wet_run(rain), rows)
        if wet:
            put("wet_hour_intensity_prev_24h_mm_per_h", math.fsum(wet) / len(wet), rows)
    cutoff = issuance - ERA5_DELAY
    for hours in (24, 72):
        rows = window(history, cutoff - hours * HOUR, hours)
        if rows:
            put(f"antecedent_rain_delayed_{hours}h_mm", math.fsum(row["rain"] for row in rows), rows)

    vintages = defaultdict(dict)
    if mode == "operational":
        for row in inputs["forecast"]:
            if (row["received_at"] <= issuance and (row["issued_at"] is None
                    or row["issued_at"] <= row["received_at"])
                    and issuance < row["valid_at"] <= issuance + TARGET):
                vintage = (row["received_at"], row["run_id"])
                vintages[vintage][row["valid_at"] - HOUR] = row
    if vintages:
        receipt, run = max(vintages)
        for hours in FORECASTS:
            rows = window(vintages[receipt, run], issuance, hours)
            if (rows and all(measurement(row["rain"]) is not None for row in rows)
                    and len({row["weather_bin"][0] for row in rows if row["weather_bin"]}) == 1
                    and all(row["weather_bin"] for row in rows)):
                put(f"forecast_rain_next_{hours}h_mm", math.fsum(row["rain"] for row in rows),
                    [row | {"available_at": receipt} for row in rows])

    for row in inputs["terrain"]:
        if row["available_at"] <= issuance:
            name = TERRAIN[row["feature"], row["unit"]]
            minimum, maximum = {
                "elevation_m": (-12000, 9000), "surface_slope_deg": (0, 90),
                "land_cover_class": (10, 100), "built_up_fraction": (0, 1),
            }[name]
            value = measurement(row["value"], minimum, maximum)
            if value is not None and (name != "land_cover_class" or value in
                                      {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}):
                put(name, value, [row])
    soil = []
    marine = []
    for row in inputs["hydrology"]:
        if row["variable"] == "soil_moisture_0_to_7cm" and cutoff - TARGET < row["valid_at"] <= cutoff:
            available = archive_available_at(row["valid_at"], row["available_at"], mode)
            if available <= issuance and measurement(row["value"], 0, 1) is not None:
                soil.append(row | {"available_at": available})
        if (mode == "operational" and row["variable"] == "sea_level_height_msl"
                and issuance - 6 * HOUR < row["valid_at"] <= issuance
                and row["available_at"] <= issuance and measurement(row["value"], -30, 30) is not None):
            marine.append(row)
    for name, candidates in (("soil_moisture_delayed", soil), ("offshore_sea_level_msl_m", marine)):
        if candidates:
            row = max(candidates, key=lambda r: (r["valid_at"], r["available_at"], r["id"]))
            put(name, row["value"], [row])

    previous = [row for row in assessed(point, inputs["observations"], issuance)
                if row["label"] == "flood_confirmed"
                and row["available_at"] < issuance
                and issuance - timedelta(days=365) <= row["observed_at"] < issuance]
    if previous:
        put("reported_flood_events_prev_365d", len({row["event_key"] for row in previous}), previous)
    return {
        "location": point["code"], "latitude": float(point["latitude"]), "longitude": float(point["longitude"]),
        "mode": mode, "issued_at": issuance, "target_end": issuance + TARGET,
        "features": features, "provenance": provenance, "weather_bins": sorted(weather_bins),
        "label": target(point, inputs["observations"], issuance, as_of),
    }
