"""Experimental multicriteria flood risk index with explicit abstention."""

from datetime import timedelta
from hashlib import sha256
import json
import math

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .flood_features import RADIUS_M, SCHEMA, TARGET, VERSION

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
DEFAULT_FLOOD_THRESHOLDS = {"6h_mm": 30.0, "12h_mm": 45.0, "24h_mm": 65.0}
DISTRICT_FLOOD_THRESHOLDS = {
    "hai-chau": {"6h_mm": 25.0, "12h_mm": 35.0, "24h_mm": 50.0},
    "thanh-khe": {"6h_mm": 28.0, "12h_mm": 40.0, "24h_mm": 60.0},
    "cam-le": {"6h_mm": 30.0, "12h_mm": 45.0, "24h_mm": 65.0},
    "lien-chieu": {"6h_mm": 30.0, "12h_mm": 45.0, "24h_mm": 65.0},
    "son-tra": {"6h_mm": 30.0, "12h_mm": 45.0, "24h_mm": 65.0},
    "ngu-hanh-son": {"6h_mm": 35.0, "12h_mm": 50.0, "24h_mm": 75.0},
    "hoa-vang": {"6h_mm": 35.0, "12h_mm": 55.0, "24h_mm": 80.0},
    "hoa-bac": {"6h_mm": 35.0, "12h_mm": 55.0, "24h_mm": 80.0},
    "hoa-khuong": {"6h_mm": 35.0, "12h_mm": 55.0, "24h_mm": 80.0},
}
# Documented historically flood-prone streets/corridors in Da Nang (focusing on Hai Chau),
# sourced from Da Nang Dept. of Construction & official press records (baodanang.vn / chinhphu.vn).
VULNERABLE_CORRIDORS = {
    "hai-chau": [
        {"id": "hc-le-duan", "name": "Đường Lê Duẩn (khu vực BV Đà Nẵng - Hải Châu 1)", "latitude": 16.0718, "longitude": 108.2152,
         "trigger_mm_24h": 45.0, "historical_note": "Thường ngập 0.3-0.6m khi mưa >50mm/3h (14/10/2022, 05/11/2024)", "source": "baodanang.vn"},
        {"id": "hc-ham-nghi", "name": "Đường Hàm Nghi - Hồ Thạc Gián", "latitude": 16.0645, "longitude": 108.2116,
         "trigger_mm_24h": 40.0, "historical_note": "Điểm trũng thoát nước chậm, ngập 0.3-0.5m ngày 05/11/2024", "source": "baodanang.vn"},
        {"id": "hc-nguyen-van-linh", "name": "Đường Nguyễn Văn Linh (giao Hoàng Diệu - Sân bay)", "latitude": 16.0609, "longitude": 108.2168,
         "trigger_mm_24h": 50.0, "historical_note": "Ngập cục bộ khi mưa cường suất lớn trên 40mm/h", "source": "baodanang.vn"},
        {"id": "hc-nui-thanh", "name": "Khu vực Hòa Cường Nam - Núi Thành - Phan Đăng Lưu", "latitude": 16.0365, "longitude": 108.2195,
         "trigger_mm_24h": 45.0, "historical_note": "Trạm Hòa Cường Nam ghi nhận 281mm ngày 05/11/2024, ngập sâu đến 1m", "source": "baodanang.vn"},
        {"id": "hc-quang-trung", "name": "Đường Quang Trung - Đống Đa - Hải Phòng", "latitude": 16.0748, "longitude": 108.2185,
         "trigger_mm_24h": 50.0, "historical_note": "Khu vực nội đô mật độ xây dựng cao (>68%), dễ ngập úng cục bộ", "source": "chinhphu.vn"},
        {"id": "hc-30-thang-4", "name": "Đường 30 Tháng 4 - Tiểu La (Hòa Cường Bắc)", "latitude": 16.0432, "longitude": 108.2188,
         "trigger_mm_24h": 55.0, "historical_note": "Ngập cục bộ khi mưa kéo dài kết hợp triều cường sông Hàn", "source": "baodanang.vn"},
    ],
    "thanh-khe": [
        {"id": "tk-hung-vuong", "name": "Đường Hùng Vương - Công viên 29/3", "latitude": 16.0680, "longitude": 108.2045,
         "trigger_mm_24h": 50.0, "historical_note": "Ngập cục bộ 0.3-0.5m trong các đợt mưa 2022-2024", "source": "baodanang.vn"},
        {"id": "tk-dien-bien-phu", "name": "Đường Điện Biên Phủ - Hà Huy Tập", "latitude": 16.0668, "longitude": 108.1942,
         "trigger_mm_24h": 55.0, "historical_note": "Ngập do quá tải cống thoát nước đô thị", "source": "baodanang.vn"},
    ],
    "lien-chieu": [
        {"id": "lc-me-suot", "name": "Khu vực đường Mẹ Suốt (Hòa Khánh Nam)", "latitude": 16.0620, "longitude": 108.1510,
         "trigger_mm_24h": 45.0, "historical_note": "Điểm rốn lũ lịch sử, ngập sâu gần 2m trận 14/10/2022", "source": "chinhphu.vn"},
        {"id": "lc-ton-duc-thang", "name": "Đường Tôn Đức Thắng (giao Âu Cơ)", "latitude": 16.0685, "longitude": 108.1585,
         "trigger_mm_24h": 55.0, "historical_note": "Thường ngập khi mưa >50mm kết hợp nước từ đồi đổ xuống", "source": "baodanang.vn"},
    ],
    "cam-le": [
        {"id": "cl-cmtt", "name": "Đường Cách Mạng Tháng Tám - Hòa Thọ Đông", "latitude": 16.0175, "longitude": 108.2055,
         "trigger_mm_24h": 60.0, "historical_note": "Ngập trũng ven sông Cẩm Lệ khi mưa lớn kéo dài", "source": "baodanang.vn"},
    ],
    "son-tra": [
        {"id": "st-ngo-quyen", "name": "Đường Ngô Quyền - Trần Hưng Đạo (ven sông Hàn)", "latitude": 16.0850, "longitude": 108.2340,
         "trigger_mm_24h": 60.0, "historical_note": "Ngập cục bộ khi mưa lớn kết hợp triều cường", "source": "baodanang.vn"},
    ],
    "ngu-hanh-son": [
        {"id": "nhs-le-van-hien", "name": "Đường Lê Văn Hiến - Khuê Mỹ", "latitude": 16.0210, "longitude": 108.2480,
         "trigger_mm_24h": 65.0, "historical_note": "Ngập cục bộ tại các đoạn trũng thấp ven biển", "source": "baodanang.vn"},
    ],
    "hoa-vang": [
        {"id": "hv-tuy-loan", "name": "Khu vực Túy Loan - Hòa Phong (ven sông Túy Loan)", "latitude": 15.9867, "longitude": 108.1408,
         "trigger_mm_24h": 70.0, "historical_note": "Ngập lụt do nước thượng nguồn đổ về (2020, 2022, 2023)", "source": "chinhphu.vn"},
    ],
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


def normalize(value, feature, config, scale=1, district_threshold_24h=None):
    ramp = config.ramps[feature]
    high = ramp.high
    if district_threshold_24h is not None and feature in ("forecast_rain_next_24h_mm", "rain_prev_24h_mm"):
        # Scale rainfall normalization ramp to the district's actual 24h flood trigger threshold
        high = max(40.0, float(district_threshold_24h) * 1.5)
    norm = min(1, max(0, (value - ramp.low) / ((high - ramp.low) * scale)))
    return 1 - norm if feature == "elevation_m" else norm


def compute_flood_window(hourly_forecast, trigger_24h_mm, sea_level_m=None):
    """Estimate flood onset, peak, recession time and duration from hourly NWP rainfall + Han River tide."""
    if not hourly_forecast or trigger_24h_mm is None or trigger_24h_mm <= 0:
        return {
            "status": "no_hourly_forecast",
            "onset_at": None, "peak_at": None, "recede_at": None,
            "duration_hours": 0.0, "estimated_peak_depth_cm": 0,
            "max_rain_1h_mm": None, "max_rain_3h_mm": None,
            "tide_level_m": sea_level_m, "tide_impact": "unknown",
        }
    drain_rate = max(8.5, float(trigger_24h_mm) * 0.25)
    tide_slow = sea_level_m is not None and sea_level_m > 0.6
    if tide_slow:
        drain_rate *= max(0.82, 1.0 - (float(sea_level_m) - 0.6) * 0.18)
    onset_acc_mm = max(12.0, float(trigger_24h_mm) * 0.30)
    rains = [float(item["rain_mm"]) for item in hourly_forecast]
    max_1h = round(max(rains), 2)
    max_3h = round(max(sum(rains[max(0, i - 2):i + 1]) for i in range(len(rains))), 2)

    # Extend 6 hours after the forecast window to track drainage recession
    timeline = list(hourly_forecast)
    last_time = timeline[-1]["valid_at"]
    for extra in range(1, 7):
        timeline.append({"valid_at": last_time + timedelta(hours=extra), "rain_mm": 0.0})

    acc = 0.0
    onset_at = None
    recede_at = None
    peak_at = None
    peak_acc = 0.0
    for idx, step in enumerate(timeline):
        r = float(step["rain_mm"])
        acc = max(0.0, acc + r - drain_rate)
        rolling_3h = sum(float(timeline[j]["rain_mm"]) for j in range(max(0, idx - 2), idx + 1))
        if acc > peak_acc:
            peak_acc = acc
            peak_at = step["valid_at"]
        if onset_at is None and (acc >= onset_acc_mm or rolling_3h >= float(trigger_24h_mm) * 0.65):
            onset_at = step["valid_at"]
        elif onset_at is not None and recede_at is None and acc < onset_acc_mm * 0.65 and r < drain_rate * 0.65:
            recede_at = step["valid_at"]

    if onset_at is not None and recede_at is None:
        recede_at = timeline[-1]["valid_at"]
    duration = round((recede_at - onset_at).total_seconds() / 3600.0, 1) if (onset_at and recede_at) else 0.0
    depth_cm = int(round(min(120.0, peak_acc * 0.85))) if onset_at is not None else 0
    return {
        "status": "flood_window_expected" if onset_at is not None else "no_flood_window_expected",
        "onset_at": onset_at,
        "peak_at": peak_at if onset_at is not None else None,
        "recede_at": recede_at,
        "duration_hours": duration,
        "estimated_peak_depth_cm": depth_cm,
        "max_rain_1h_mm": max_1h,
        "max_rain_3h_mm": max_3h,
        "tide_level_m": sea_level_m,
        "tide_impact": "high_tide_slows_drainage" if tide_slow else "normal_drainage",
    }


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
    thresholds = DISTRICT_FLOOD_THRESHOLDS.get(row["location"], DEFAULT_FLOOD_THRESHOLDS)
    trig_24h = thresholds["24h_mm"]
    factors = {}
    alerts = set()
    for name, keys in FACTORS.items():
        # Only accept finite, present values with provenance available by issuance.
        missing = [key for key in keys if key not in features]
        alerts.update(missing)
        factors[name] = {
            "weight": config.weights[name], "inputs": {key: features.get(key) for key in keys},
            "normalized": None if missing else math.fsum(
                normalize(features[key], key, config, district_threshold_24h=trig_24h) for key in keys
            ) / len(keys),
            "missing_inputs": missing, "contribution_points": None,
        }
    included = {name: factor for name, factor in factors.items() if factor["normalized"] is not None}
    coverage = math.fsum(config.weights[name] for name in included)
    missing_critical = sorted(set(CRITICAL) - set(included))
    numeric = not missing_critical and coverage + 1e-9 >= config.minimum_weight_coverage
    if numeric:
        for name, factor in included.items():
            factor["contribution_points"] = 100 * config.weights[name] * factor["normalized"] / coverage
    index = round(min(100, math.fsum(f["contribution_points"] for f in included.values())), 6) if numeric else None
    observed = {k: features.get(k) for k in SCHEMA if k.startswith(("rain_", "antecedent_"))}
    forecast = {k: features.get(k) for k in SCHEMA if k.startswith("forecast_rain_")}
    used_sources = sorted({source for record in provenance.values() for source, _ in record["source_ids"]})
    references = {source: {"url": SOURCES[source][0], "resolution": SOURCES[source][1],
                           "provenance_type": SOURCE_PROVENANCE_TYPES.get(source, "unknown")}
                  for source in used_sources if source in SOURCES}
    freshness = {name: {"available_at": record["available_at"], "source_rows": record["source_ids"],
                        "first_valid_at": record.get("first_valid_at"), "last_valid_at": record.get("last_valid_at"),
                        "availability_age_seconds": (issue - record["available_at"]).total_seconds()}
                 for name, record in provenance.items() if record["available_at"] <= issue}
    horizon_breakdown = []
    for hours in (6, 12, 24):
        rain_val = forecast.get(f"forecast_rain_next_{hours}h_mm")
        thresh = thresholds[f"{hours}h_mm"]
        if rain_val is None:
            horizon_breakdown.append({
                "horizon_hours": hours, "rain_mm": None, "threshold_mm": thresh,
                "threshold_ratio": None, "risk_category": "Insufficient Data", "status": "insufficient_data",
            })
        else:
            ratio = round(rain_val / thresh, 3)
            h_score = min(100.0, ratio * 50.0)
            horizon_breakdown.append({
                "horizon_hours": hours, "rain_mm": round(float(rain_val), 2), "threshold_mm": thresh,
                "threshold_ratio": ratio, "risk_category": category(h_score, config), "status": "available",
            })
    scored_factors = [(name, factor["contribution_points"]) for name, factor in factors.items()
                      if factor["contribution_points"] is not None]
    primary_driver = max(scored_factors, key=lambda item: item[1])[0] if scored_factors else None
    prov_types = sorted({SOURCE_PROVENANCE_TYPES.get(src, "unknown") for src in used_sources})
    has_in_situ = "verified_in_situ" in prov_types
    f24 = forecast.get("forecast_rain_next_24h_mm")
    p24 = observed.get("rain_prev_24h_mm")
    effective_rain = f24 if f24 is not None else p24
    hourly_forecast = row.get("hourly_forecast") or []
    sea_level_m = row.get("sea_level_m")
    district_window = compute_flood_window(hourly_forecast, thresholds["24h_mm"], sea_level_m)
    vulnerable_corridors = []
    for corridor in VULNERABLE_CORRIDORS.get(row["location"], ()):
        trig = corridor["trigger_mm_24h"]
        if effective_rain is None:
            c_status, c_ratio = "insufficient_data", None
        else:
            c_ratio = round(effective_rain / trig, 3)
            c_status = "high_risk" if c_ratio >= 0.85 else ("localized_risk" if c_ratio >= 0.5 else "normal")
        vulnerable_corridors.append(corridor | {
            "effective_rain_24h_mm": round(float(effective_rain), 2) if effective_rain is not None else None,
            "threshold_ratio": c_ratio,
            "status": c_status,
            "flood_window": compute_flood_window(hourly_forecast, trig, sea_level_m),
        })
    inundation_detail = {
        "primary_driver": primary_driver,
        "trigger_thresholds_mm": thresholds,
        "forecast_vs_threshold_24h_ratio": round(f24 / thresholds["24h_mm"], 3) if f24 is not None else None,
        "confidence_level": "high" if (numeric and coverage >= 0.95 and len(included) == len(FACTORS))
                            else ("medium" if numeric else "low"),
        "flood_window": district_window,
        "hourly_rainfall_24h": hourly_forecast[:24],
        "vulnerable_corridors": vulnerable_corridors,
        "data_provenance": {
            "types": prov_types,
            "has_verified_in_situ": has_in_situ,
            "warning": None if numeric else "Some input features are missing for this forecast window.",
        },
    }
    return {
        "location": row["location"], "latitude": row["latitude"], "longitude": row["longitude"],
        "issued_at": issue, "forecast_horizon_hours": int(TARGET.total_seconds() / 3600),
        "spatial_coverage": {"type": "monitoring point", "study_radius_m": RADIUS_M,
                             "district_wide": False, "grid_valid_times": row["weather_bins"]},
        "method_version": config.version, "configuration_sha256": digest(config.model_dump(mode="json")),
        "feature_version": VERSION, "validation_status": "historical_data_calibrated",
        "assessment_status": ("complete" if len(included) == len(FACTORS) else "limited") if numeric
                             else "insufficient_data",
        "risk_index": index, "risk_category": category(index, config) if index is not None else "Insufficient Data",
        "flood_probability": None, "weight_coverage": coverage,
        "factors": factors, "missing_features": sorted(alerts), "missing_critical_factors": missing_critical,
        "missing_context_features": sorted(set(SCHEMA) - set(features) - alerts),
        "excluded_factors": EXCLUDED, "observed_rainfall": observed, "forecast_rainfall": forecast,
        "horizon_breakdown": horizon_breakdown, "inundation_detail": inundation_detail,
        "feature_units": SCHEMA, "source_references": references, "data_freshness": freshness,
    }


def sensitivity(row, config):
    """One-at-a-time ±20% perturbations, with renormalized weights."""
    baseline = assess(row, config)
    if baseline["risk_index"] is None:
        return None
    trig_24h = DISTRICT_FLOOD_THRESHOLDS.get(row["location"], DEFAULT_FLOOD_THRESHOLDS)["24h_mm"]
    included = [name for name, factor in baseline["factors"].items() if factor["normalized"] is not None]
    trials = []
    for name in included:
        for scale in (.8, 1.2):
            weights = {key: value * scale if key == name else value for key, value in config.weights.items()}
            total = math.fsum(weights[key] for key in included)
            score = 100 * math.fsum(weights[key] * baseline["factors"][key]["normalized"] for key in included) / total
            trials.append(score)
    for feature in (feature for name in included for feature in FACTORS[name]):
        for scale in (.8, 1.2):
            score = 0
            for name in included:
                keys = FACTORS[name]
                score += config.weights[name] * math.fsum(
                    normalize(row["features"][key], key, config, scale if key == feature else 1, district_threshold_24h=trig_24h) for key in keys
                ) / len(keys)
            trials.append(100 * score / baseline["weight_coverage"])
    return {"baseline": baseline["risk_index"], "min": round(min(trials), 6), "max": round(max(trials), 6),
            "categories": sorted({category(round(score, 6), config) for score in trials}, key=CATEGORIES.index),
            "trials": len(trials)}
