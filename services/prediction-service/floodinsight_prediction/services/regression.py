from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import make_pipeline
from xgboost import XGBRegressor

from floodinsight_ml.daily import FEATURES, split_metadata


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
            tree_method="hist",       # Fast histogram-based splitting
            eval_metric="mae",
        ),
    )
    model.fit(train[FEATURES].astype(float), train["target"])
    metrics = {}
    for name in ("validation", "test"):
        split = parts[name]
        pred = model.predict(split[FEATURES].astype(float)).clip(min=0)
        metrics[name] = {
            "xgboost": errors(split["target"], pred),
            "lag_8_persistence": errors(split["target"], split["rain_d8"]),
        }
    return model, split_metadata(parts), metrics
