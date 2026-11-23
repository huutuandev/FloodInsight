import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from floodinsight_ml.storage import DataUnavailable

FEATURES = ["rainfall", "intensity", "rainy_hours", "humidity", "temperature", "wind"]


def train_clusters(rows, clusters=3, scan_k=False):
    values = pd.DataFrame(rows, columns=FEATURES).astype(float)
    if len(values) <= 2 or values.isna().all().any():
        raise DataUnavailable("Provide more complete-rain days than clusters and data for every feature")
    preprocessing = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    scaled = preprocessing.fit_transform(values)

    scan_scores = None
    selected_clusters = clusters
    if scan_k:
        scan_scores = {}
        distinct_periods = len(np.unique(scaled, axis=0))
        for k in range(2, 7):
            if k >= len(values) or k > distinct_periods:
                continue
            candidate = KMeans(n_clusters=k, n_init=20, random_state=42).fit(scaled)
            if len(set(candidate.labels_)) < 2:
                continue
            sample = min(len(values), 5000)
            try:
                score = float(silhouette_score(
                    scaled, candidate.labels_,
                    sample_size=sample if sample < len(values) else None,
                    random_state=42,
                ))
            except ValueError:
                continue
            scan_scores[str(k)] = score
        if not scan_scores:
            raise DataUnavailable("No valid cluster counts could be evaluated")
        selected_clusters = int(max(scan_scores, key=scan_scores.get))
    if len(values) <= selected_clusters:
        raise DataUnavailable("Provide more complete-rain days than clusters")
    if len(np.unique(scaled, axis=0)) < selected_clusters:
        raise DataUnavailable("There are too few distinct weather periods for this cluster count")
    model = KMeans(n_clusters=selected_clusters, n_init=20, random_state=42).fit(scaled)
    if len(set(model.labels_)) < 2:
        raise DataUnavailable("Clustering produced fewer than two distinct groups")
    pca = PCA(n_components=2).fit(scaled)
    sample = min(len(values), 5000)
    # Seeded sampling may omit a tiny cluster, so require a defined sampled score.
    try:
        score = float(silhouette_score(
            scaled, model.labels_,
            sample_size=sample if sample < len(values) else None,
            random_state=42,
        ))
    except ValueError as exc:
        raise DataUnavailable("Could not evaluate the silhouette on the available groups") from exc
    stats = []
    for label in sorted(set(model.labels_)):
        group = values.loc[model.labels_ == label]
        stats.append({
            "label": int(label), "days": len(group),
            "means": {key: None if pd.isna(mean) else float(mean) for key, mean in group.mean().items()},
        })
    return {"preprocessing": preprocessing, "model": model, "pca": pca}, {
        "samples": len(values), "silhouette_score": score, "silhouette_sample_size": sample,
        "requested_clusters": clusters,
        "selected_clusters": selected_clusters,
        "silhouette_scores": scan_scores,
        "pca_explained_variance": pca.explained_variance_ratio_.tolist(),
        "cluster_statistics": stats, "features": FEATURES,
    }


def apply_clusters(rows, artifact):
    if not rows:
        raise DataUnavailable("No complete-rain days in this window")
    frame = pd.DataFrame(rows, columns=FEATURES).astype(float)
    scaled = artifact["preprocessing"].transform(frame)
    labels = artifact["model"].predict(scaled)
    coords = artifact["pca"].transform(scaled)
    return [(int(label), {"pc1": float(x), "pc2": float(y)}) for label, (x, y) in zip(labels, coords)]
