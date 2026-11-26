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
            tree_method="hist",
            eval_metric="mae",
        ),
    )
    model.fit(train[FEATURES].astype(float), train["target"])
    metrics = {}
    for name in ("validation", "test"):
        split = parts[name]
        metrics[name] = {
            "xgboost": errors(split["target"], model.predict(split[FEATURES].astype(float))),
            "lag_1_persistence": errors(split["target"], split["rain_d1"]),
        }
    return model, split_metadata(parts), metrics


def calibrate_prediction(location_code: str, target_date, raw_ml_val: float) -> float:
    """Blend live Open-Meteo NWP + ECMWF/GFS with XGBoost for accurate daily rainfall prediction."""
    live_rain, ecmwf, gfs = None, None, None
    try:
        with connect() as conn:
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

    ml_val = max(0.0, float(raw_ml_val))
    primary_nwp = live_rain if live_rain is not None else ecmwf
    if primary_nwp is not None:
        secondary_nwp = ecmwf if (live_rain is not None and ecmwf is not None) else (gfs if gfs is not None else primary_nwp)
        base_val = 0.65 * primary_nwp + 0.15 * secondary_nwp + 0.20 * ml_val
    else:
        base_val = 0.0 if ml_val < 0.3 else ml_val

    return round(float(max(0.0, base_val)), 2)

