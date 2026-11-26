"""Experimental multicriteria flood risk index with explicit abstention."""

from hashlib import sha256
import json
import math

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .flood_features import LIVE_SOIL, RADIUS_M, SCHEMA, TARGET, VERSION

FACTORS = {
    "forecast_rainfall": ("forecast_rain_next_24h_mm",),
    "recent_rainfall": ("rain_prev_24h_mm",),
    "rainfall_intensity": ("rain_max_hour_prev_24h_mm",),
    "terrain": ("elevation_m", "built_up_fraction"),
    "soil_wetness": ("soil_moisture_delayed",),
}
CRITICAL = tuple(FACTORS)[:-1]
CATEGORIES = ("Low", "Moderate", "High", "Very High")
EXCLUDED = {
    "river_conditions": "No verified reach-specific discharge or stage series",
    "historical_susceptibility": "No qualifying point flood history or surveillance denominator",
    "slope": "No locally validated direction or response curve for this DSM-derived slope",
    "offshore_sea_level": "No verified tide-to-site relationship or compatible local stage datum",
}
SOURCES = {
    "open-meteo-forecast-api": ("https://open-meteo.com/en/docs", "platform/model dependent"),
    "open-meteo-archive-era5": ("https://open-meteo.com/en/docs/historical-weather-api", "0.25 degrees"),
    "copernicus-dem-glo30": ("https://registry.opendata.aws/copernicus-dem/", "1 arc-second in the study area"),
    "esa-worldcover-2021-v200": ("https://esa-worldcover.org/en/data-access", "10 m cells, 11×11 neighborhood"),
    "open-meteo-marine": ("https://open-meteo.com/en/docs/marine-weather-api", "approximately 8 km"),
    "vietnam-vrain-haichau-ground-truth": ("https://vrain.vn", "verified in-situ rain gauge"),
}
SOURCE_PROVENANCE_TYPES = {
    "open-meteo-forecast-api": "nwp_forecast",
    "open-meteo-ecmwf-ifs": "nwp_forecast",
    "open-meteo-gfs-seamless": "nwp_forecast",
    "open-meteo-archive-era5": "reanalysis_grid",
    "vietnam-vrain-haichau-ground-truth": "verified_in_situ",
    "copernicus-dem-glo30": "terrain_dem_landcover",
    "esa-worldcover-2021-v200": "terrain_dem_landcover",
    "open-meteo-marine": "marine_grid",
}
class Ramp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    low: FiniteFloat
    high: FiniteFloat

    @model_validator(mode="after")
    def ordered(self):
        if self.high <= self.low:
            raise ValueError("Ramp high must exceed low")
        return self


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(default="flood-risk-v1", min_length=1, max_length=80)
    weights: dict[str, FiniteFloat] = Field(default_factory=lambda: dict(zip(FACTORS, (.40, .20, .15, .15, .10))))
    ramps: dict[str, Ramp] = Field(default_factory=lambda: {
        feature: Ramp(low=low, high=high) for feature, (low, high) in {
            "forecast_rain_next_24h_mm": (0, 100), "rain_prev_24h_mm": (0, 100),
            "rain_max_hour_prev_24h_mm": (0, 50), "elevation_m": (0, 20),
            "built_up_fraction": (0, 1), "soil_moisture_delayed": (.20, .50),
        }.items()
    })
    category_starts: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (25, 50, 75)
    minimum_weight_coverage: FiniteFloat = .90

    @model_validator(mode="after")
    def valid(self):
        if (set(self.weights) != set(FACTORS) or any(not 0 < w <= 1 for w in self.weights.values())
                or not math.isclose(math.fsum(self.weights.values()), 1, abs_tol=1e-9)):
            raise ValueError("Provide positive weights for all factors, summing to 1")
        if set(self.ramps) != {feature for features in FACTORS.values() for feature in features}:
            raise ValueError("Provide a normalization ramp for every scored feature")
        low, high, very_high = self.category_starts
        if not (0 < low < high < very_high < 100 and 0 < self.minimum_weight_coverage <= 1):
            raise ValueError("Invalid category boundaries or coverage")
        return self


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def category(score, config):
    return CATEGORIES[sum(score >= boundary for boundary in config.category_starts)]


def normalize(value, feature, config, scale=1):
    ramp = config.ramps[feature]
    norm = min(1, max(0, (value - ramp.low) / ((ramp.high - ramp.low) * scale)))
    return 1 - norm if feature == "elevation_m" else norm


def assess(row, config):
    if row["mode"] != "operational":
        raise ValueError("Risk assessment requires recorded-receipt operational features")
    issue = row["issued_at"]
    provenance = row["provenance"]
    features = {
        key: value for key, value in row["features"].items()
        if type(value) in (int, float) and math.isfinite(value) and key in provenance
        and provenance[key]["available_at"] <= issue
    }
    factors = {}
    alerts = set()
    for name, keys in FACTORS.items():
        # Only accept finite, present values with provenance available by issuance.
        missing = [key for key in keys if key not in features]
        alerts.update(missing)
        factors[name] = {
            "weight": config.weights[name], "inputs": {key: features.get(key) for key in keys},
            "normalized": None if missing else math.fsum(normalize(features[key], key, config) for key in keys) / len(keys),
            "missing_inputs": missing, "contribution_points": None,
        }
    included = {name: factor for name, factor in factors.items() if factor["normalized"] is not None}
    coverage = math.fsum(config.weights[name] for name in included)
    missing_critical = sorted(set(CRITICAL) - set(included))
    numeric = not missing_critical and coverage + 1e-9 >= config.minimum_weight_coverage
    limited = len(included) != len(FACTORS)
    if numeric:
        for name, factor in included.items():
            factor["contribution_points"] = 100 * config.weights[name] * factor["normalized"]
    index = round(min(100, math.fsum(f["contribution_points"] for f in included.values())), 6) if numeric else None
    observed = {k: features.get(k) for k in SCHEMA if k.startswith(("rain_", "antecedent_"))}
    forecast = {k: features.get(k) for k in SCHEMA if k.startswith("forecast_rain_")}
    modeled_rain = any(source == "open-meteo-forecast-api" for key in ("rain_prev_24h_mm", "rain_max_hour_prev_24h_mm")
                       for source, _ in provenance.get(key, {}).get("source_ids", ()))
    method = config.version + "-modeled" if row.get("uses_operational_precipitation") else config.version
    method += "-limited" if limited and numeric else ""
    used_sources = sorted({source for record in provenance.values() for source, _ in record["source_ids"]})
    references = {source: {"url": SOURCES[source][0], "resolution": SOURCES[source][1],
                           "provenance_type": SOURCE_PROVENANCE_TYPES.get(source, "unknown")}
                  for source in used_sources if source in SOURCES}
    freshness = {name: {"available_at": record["available_at"], "source_rows": record["source_ids"],
                        "first_valid_at": record.get("first_valid_at"), "last_valid_at": record.get("last_valid_at"),
                        "availability_age_seconds": (issue - record["available_at"]).total_seconds()}
                 for name, record in provenance.items() if record["available_at"] <= issue}
    scored_factors = [(name, factor["contribution_points"]) for name, factor in factors.items()
                      if factor["contribution_points"] is not None]
    primary_driver = max(scored_factors, key=lambda item: item[1])[0] if scored_factors else None
    prov_types = sorted({SOURCE_PROVENANCE_TYPES.get(src, "unknown") for src in used_sources})
    has_in_situ = "verified_in_situ" in prov_types
    inundation_detail = {
        "primary_driver": primary_driver,
        "data_provenance": {
            "types": prov_types,
            "has_verified_in_situ": has_in_situ,
            "warning": None if numeric else "Some input features are missing for this forecast window.",
        },
    }
    return {
        "location": row["location"], "latitude": row["latitude"], "longitude": row["longitude"],
        "issued_at": issue, "target_end": row.get("target_end", issue + TARGET),
        "forecast_horizon_hours": int(TARGET.total_seconds() / 3600),
        "spatial_coverage": {"type": "monitoring point", "study_radius_m": RADIUS_M,
                             "district_wide": False, "grid_valid_times": row["weather_bins"]},
        "method_version": method, "configuration_sha256": digest(config.model_dump(mode="json")),
        "feature_version": VERSION + "-modeled" if row.get("uses_operational_precipitation") else VERSION, "validation_status": "experimental_heuristic_unvalidated",
        "assessment_status": ("complete" if len(included) == len(FACTORS) else "limited") if numeric
                             else "insufficient_data",
        "risk_index": index, "risk_category": category(index, config) if index is not None else "Insufficient Data",
        "flood_probability": None, "weight_coverage": coverage,
        "factors": factors, "missing_features": sorted(alerts), "missing_critical_factors": missing_critical,
        "missing_context_features": sorted(set(SCHEMA) - set(features) - alerts),
        "excluded_factors": EXCLUDED, "observed_rainfall": observed, "forecast_rainfall": forecast,
        "inundation_detail": inundation_detail,
        "recent_rainfall_type": "modeled_estimate" if modeled_rain else "reanalysis",
        "modeled_soil_moisture": {k: features.get(k) for k in LIVE_SOIL},
        "feature_units": SCHEMA | LIVE_SOIL, "source_references": references, "data_freshness": freshness,
    }


def sensitivity(row, config):
    """One-at-a-time ±20% perturbations, with renormalized weights."""
    baseline = assess(row, config)
    if baseline["risk_index"] is None:
        return None
    included = [name for name, factor in baseline["factors"].items() if factor["normalized"] is not None]
    trials = []
    for name in included:
        for scale in (.8, 1.2):
            weights = {key: value * scale if key == name else value for key, value in config.weights.items()}
            total = math.fsum(weights.values())
            score = 100 * math.fsum(weights[key] * baseline["factors"][key]["normalized"] for key in included) / total
            trials.append(score)
    for feature in (feature for name in included for feature in FACTORS[name]):
        for scale in (.8, 1.2):
            score = 0
            for name in included:
                keys = FACTORS[name]
                score += config.weights[name] * math.fsum(
                    normalize(row["features"][key], key, config, scale if key == feature else 1) for key in keys
                ) / len(keys)
            trials.append(100 * score)
    return {"baseline": baseline["risk_index"], "min": round(min(trials), 6), "max": round(max(trials), 6),
            "categories": sorted({category(round(score, 6), config) for score in trials}, key=CATEGORIES.index),
            "trials": len(trials)}
