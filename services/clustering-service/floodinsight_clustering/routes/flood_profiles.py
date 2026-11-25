"""Exploratory clustering of complete point-level terrain profiles."""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Query
import numpy as np
from pydantic import AwareDatetime
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from floodinsight_ml.api import warehouse_errors
from floodinsight_ml.flood_features import VERSION
from floodinsight_ml.flood_store import current_features, resolve_issuance
from floodinsight_ml.storage import DataUnavailable, connect

router = APIRouter(prefix="/clustering", tags=["experimental flood profiles"])
COLUMNS = ("elevation_m", "surface_slope_deg", "built_up_fraction")


def profiles(rows, count):
    complete = [row for row in rows if all(row["features"][name] is not None for name in COLUMNS)]
    values = np.asarray([[row["features"][name] for name in COLUMNS] for row in complete], dtype=float)
    if len(complete) < 2 * count or len(np.unique(values, axis=0)) < 2 * count:
        raise DataUnavailable("Need at least two distinct complete point profiles per requested group")
    scaled = StandardScaler().fit_transform(values)
    fit = KMeans(n_clusters=count, n_init=20, random_state=42).fit(scaled)
    if len(set(fit.labels_)) != count:
        raise DataUnavailable("Could not separate the requested number of groups")
    return {
        "method_version": "flood-terrain-profiles-v1", "feature_version": VERSION,
        "interpretation": "Exploratory group IDs for terrain profiles without flood labels or risk ordering",
        "features": COLUMNS, "complete_points": len(complete), "excluded_points": len(rows) - len(complete),
        "cluster_sizes": dict(Counter(int(label) for label in fit.labels_)),
        "silhouette_in_sample": float(silhouette_score(scaled, fit.labels_)),
        "assignments": [{"location": row["location"], "cluster_id": int(label),
                         "features": {name: row["features"][name] for name in COLUMNS}}
                        for row, label in zip(complete, fit.labels_)],
    }


@router.get("/flood-profiles")
@warehouse_errors
def flood_profiles(issued_at: AwareDatetime | None = None, clusters: Annotated[int, Query(ge=2, le=5)] = 2):
    try:
        issuance = resolve_issuance(issued_at)
    except ValueError as exc:
        raise DataUnavailable(str(exc)) from exc
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        rows = list(current_features(conn, issuance))
    return profiles(rows, clusters) | {"issued_at": issuance}
