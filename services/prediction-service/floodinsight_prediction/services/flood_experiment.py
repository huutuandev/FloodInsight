"""Run a retrospective, event-separated flood experiment from warehouse evidence."""
import json

from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from floodinsight_ml.storage import connect


def evidence():
    with connect() as conn:
        return conn.execute("""
            SELECT e.id AS event, e.event_date, r.place, coalesce(r.site_location,e.location) AS district,
                   r.status, r.depth_cm, r.elevation_m, forecast.rainfall_mm
            FROM flood_reports r JOIN flood_events e ON e.id=r.event_id
            LEFT JOIN LATERAL (
                SELECT p.rainfall_mm FROM prediction_results p
                JOIN dim_location l ON p.location_id=l.id
                JOIN model_versions m ON m.id=p.model_version_id
                WHERE l.code=coalesce(r.site_location,e.location)
                  AND m.model_name='seven-day-rainfall-regressors'
                  AND p.target_hour_utc=warehouse_local_day_start(e.event_date)
                  AND p.issued_at >= warehouse_local_day_start(e.event_date - 1)
                  AND p.issued_at < warehouse_local_day_start(e.event_date)
                ORDER BY p.issued_at DESC, m.version LIMIT 1
            ) forecast ON true
            WHERE r.status IN ('confirmed_dry','flooded')
            ORDER BY e.event_date, e.id, r.id
        """).fetchall()


def evaluate(rows):
    usable = [r for r in rows if r["rainfall_mm"] is not None and r["elevation_m"] is not None]
    scores = {name: dict(hits=0, misses=0, false_alarms=0, correct_dry=0)
              for name in ("rain_25mm", "logistic")}
    tested = set()
    for date in sorted({r["event_date"] for r in usable}):
        train = [r for r in usable if r["event_date"] < date]
        if len({r["status"] for r in train}) < 2:
            continue
        def features(r):
            return [float(r["rainfall_mm"]), float(r["elevation_m"])]
        model = make_pipeline(StandardScaler(), LogisticRegression(random_state=0))
        model.fit([features(r) for r in train], [r["status"] == "flooded" for r in train])
        for row in (r for r in usable if r["event_date"] == date):
            tested.add(row["event"])
            actual = row["status"] == "flooded"
            for name, forecast in (("rain_25mm", row["rainfall_mm"] >= 25),
                                   ("logistic", model.predict([features(row)])[0])):
                metric = ("hits" if forecast else "misses") if actual else (
                    "false_alarms" if forecast else "correct_dry")
                scores[name][metric] += 1
    return {"observations": len(rows), "complete_features": len(usable),
            "tested_events": len(tested), "scores": scores if tested else None}


def cluster_sites(rows):
    # Compare sites only across the same surveyed events; absent reports remain missing.
    profiles = {}
    for r in rows:
        site = (r["district"], r["place"])
        profiles.setdefault(site, {}).setdefault(r["event"], set()).add(r["status"])
    groups = {}
    for site, events in profiles.items():
        if len(events) >= 2 and all(len(labels) == 1 for labels in events.values()):
            groups.setdefault(tuple(sorted(events)), []).append(site)
    output = []
    for events, sites in groups.items():
        matrix = [tuple(int("flooded" in profiles[site][e]) for e in events) for site in sites]
        if len(sites) < 3 or len(set(matrix)) < 2:
            continue
        labels = KMeans(n_clusters=2, random_state=0, n_init=10).fit_predict(matrix)
        output.append({"events": events, "sites": [
            {"district": s[0], "place": s[1], "cluster": int(label)}
            for s, label in zip(sites, labels)]})
    return output


if __name__ == "__main__":
    rows = evidence()
    print(json.dumps({"validation": evaluate(rows), "clusters": cluster_sites(rows)}, ensure_ascii=False))
