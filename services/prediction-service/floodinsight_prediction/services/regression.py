from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import make_pipeline
from xgboost import XGBRegressor

from floodinsight_ml.daily import FEATURES, split_metadata


def errors(actual, predicted):
    return {"mae_mm": float(mean_absolute_error(actual, predicted)),
            "rmse_mm": float(root_mean_squared_error(actual, predicted))}


def climatology_predictions(train, split):
    monthly = train.assign(month=train["target_date"].map(lambda value: value.month)).groupby("month")["target"].mean()
    fallback = float(train["target"].mean())
    predictions = split["target_date"].map(lambda value: value.month).map(monthly).fillna(fallback).astype(float)
    return predictions


def monthly_climatology(train):
    monthly = train.assign(month=train["target_date"].map(lambda value: value.month)).groupby("month")["target"].mean()
    return monthly.to_dict(), float(train["target"].mean())


def residual_predictions(model, train, split):
    monthly, fallback = monthly_climatology(train)
    climate = split["target_date"].map(lambda value: monthly.get(value.month, fallback)).astype(float)
    residual = model.predict(split[FEATURES].astype(float))
    return (climate + residual).clip(lower=0)


def train_regressor(parts, residual_on_climatology=False, simple_tree=False):
    train = parts["train"]
    monthly, fallback = monthly_climatology(train)
    if residual_on_climatology:
        train_target = train["target"] - train["target_date"].map(lambda value: monthly.get(value.month, fallback)).astype(float)
    else:
        train_target = train["target"]
    forest_options = {"n_estimators": 200, "random_state": 42, "n_jobs": 2}
    if simple_tree:
        forest_options.update(max_depth=5, min_samples_leaf=10)
    else:
        forest_options.update(min_samples_leaf=3)
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestRegressor(**forest_options) if residual_on_climatology or simple_tree else XGBRegressor(
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
    model.fit(train[FEATURES].astype(float), train_target)
    model.residual_on_climatology = residual_on_climatology
    model.monthly_climatology = monthly
    model.monthly_climatology_fallback = fallback
    model.simple_tree = simple_tree
    metrics = {}
    for name in ("validation", "test"):
        split = parts[name]
        climate = climatology_predictions(train, split)
        if residual_on_climatology:
            predicted = residual_predictions(model, train, split).clip(lower=0)
        else:
            predicted = model.predict(split[FEATURES].astype(float)).clip(min=0)
        model_name = "residual_climatology_simple_tree" if residual_on_climatology and simple_tree else (
            "residual_climatology" if residual_on_climatology else ("random_forest" if simple_tree else "xgboost")
        )
        metrics[name] = {
            model_name: errors(split["target"], predicted),
            "lag_8_persistence": errors(split["target"], split["rain_d8"]),
            "month_climatology": errors(split["target"], climate),
        }
    return model, split_metadata(parts), metrics
