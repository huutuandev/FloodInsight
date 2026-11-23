from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import make_pipeline

from floodinsight_ml.daily import FEATURES, split_metadata


def errors(actual, predicted):
    return {"mae_mm": float(mean_absolute_error(actual, predicted)),
            "rmse_mm": float(root_mean_squared_error(actual, predicted))}


def climatology_predictions(train, split):
    monthly = train.assign(month=train["target_date"].map(lambda value: value.month)).groupby("month")["target"].mean()
    fallback = float(train["target"].mean())
    predictions = split["target_date"].map(lambda value: value.month).map(monthly).fillna(fallback).astype(float)
    return predictions


def train_regressor(parts):
    train = parts["train"]
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestRegressor(n_estimators=200, min_samples_leaf=3, random_state=42, n_jobs=2),
    )
    model.fit(train[FEATURES].astype(float), train["target"])
    metrics = {}
    for name in ("validation", "test"):
        split = parts[name]
        metrics[name] = {
            "random_forest": errors(split["target"], model.predict(split[FEATURES].astype(float))),
            "lag_8_persistence": errors(split["target"], split["rain_d8"]),
            "month_climatology": errors(split["target"], climatology_predictions(train, split)),
        }
    return model, split_metadata(parts), metrics

