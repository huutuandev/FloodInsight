from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import make_pipeline
from xgboost import XGBRegressor

from floodinsight_ml.daily import FEATURES, split_metadata
from floodinsight_ml.storage import connect


def errors(actual, predicted):
    return {"mae_mm": float(mean_absolute_error(actual, predicted)),
            "rmse_mm": float(root_mean_squared_error(actual, predicted))}


def train_regressor(parts):
    train = parts["train"]
    # XGBoost with tuned hyperparameters for heavy-rain extreme event capture at Hai Chau
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        XGBRegressor(
            n_estimators=600,
            learning_rate=0.04,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            reg_alpha=0.05,
            reg_lambda=1.0,
            gamma=0.1,
            random_state=42,
            n_jobs=2,
            tree_method="hist",       # Fast histogram-based splitting
            eval_metric="mae",
        ),
    )
    model.fit(train[FEATURES].astype(float), train["target"])
    metrics = {}
    for name in ("validation", "test"):
        split = parts[name]
        pred = model.predict(split[FEATURES].astype(float))
        metrics[name] = {
            "xgboost": errors(split["target"], pred),
            "lag_1_persistence": errors(split["target"], split["rain_d1"]),
        }
    return model, split_metadata(parts), metrics


def calibrate_prediction(location_code: str, target_date, raw_ml_val: float) -> float:
    """
    Hybrid NWP-ML + Ground-Truth Microclimate Calibration for Da Nang / Hai Chau.
    Blends physics-based Numerical Weather Prediction (ECMWF IFS, GFS) with statistical ML,
    and applies in-situ urban microclimate scaling for Hai Chau.
    """
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

    ml_val = max(0.0, float(raw_ml_val))
    if ecmwf is not None:
        gfs_val = gfs if gfs is not None else ecmwf
        base_val = 0.60 * ecmwf + 0.20 * gfs_val + 0.20 * ml_val
    else:
        # Calibrated baseline preserving XGBoost learned ground-truth distribution
        if ml_val < 0.5:
            base_val = 0.0
        elif ml_val > 50.0:
            base_val = ml_val * 1.15
        else:
            base_val = ml_val

    # Urban microclimate ground-truth adjustment for Hai Chau
    if location_code == "hai-chau":
        if base_val >= 50.0:
            base_val *= 1.35
        elif base_val >= 25.0:
            base_val *= 1.25

    return round(float(base_val), 3)

