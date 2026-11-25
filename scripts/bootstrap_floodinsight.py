"""Recover the running Compose project using persisted warehouse checkpoints."""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import sleep
from urllib.error import URLError
from urllib.request import urlopen

from recover_dashboard import APIError, api, process, span


ROOT = Path(__file__).resolve().parents[1]
POINTS = {"cam-le", "hai-chau", "lien-chieu", "ngu-hanh-son", "thanh-khe"}
RASTERS = {
    "copernicus-dem": (
        "https://copernicus-dem-30m.s3.amazonaws.com/"
        "Copernicus_DSM_COG_10_N16_00_E108_00_DEM/Copernicus_DSM_COG_10_N16_00_E108_00_DEM.tif",
        "copernicus-dem-glo30", {"elevation", "surface_slope"},
    ),
    "worldcover": (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N15E108_Map.tif",
        "esa-worldcover-2021-v200", {"worldcover_class", "worldcover_built_up_fraction_11x11"},
    ),
}


def log(stage, data):
    print(stage, json.dumps(data, ensure_ascii=True, default=str), flush=True)


def retry(operation, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (APIError, URLError, TimeoutError, subprocess.CalledProcessError) as error:
            if isinstance(error, APIError) and error.status not in {409, 429, 500, 502, 503, 504}:
                raise
            if attempt == attempts:
                raise
            log("retry", {"attempt": attempt, "error": str(error)})
            sleep(2 ** attempt)


def run(command, *, output=False):
    return subprocess.run(command, cwd=ROOT, check=True, text=True,
                          encoding="utf-8", stdout=subprocess.PIPE if output else None).stdout


def command(compose, module, *args, output=False):
    shared = ROOT / "services/ml-common"
    return run([*compose, "run", "-T", "--rm", "--no-deps",
                "-v", f"{shared}:/opt/ml-common:ro", "-e", "PYTHONPATH=/opt/ml-common:/app", "warehouse-service",
                "python", "-m", module, *args], output=output)


def import_rasters(compose, coverage):
    for name, (url, source, features) in RASTERS.items():
        existing = {(row["point"], row["feature"]) for row in coverage["terrain"] if row["source"] == source}
        if all((point, feature) in existing for point in POINTS for feature in features):
            log("raster checkpoint", name)
            continue
        with TemporaryDirectory(prefix="floodinsight-raster-") as directory:
            def download():
                with urlopen(url, timeout=90) as response, (Path(directory) / "source.tif").open("wb") as target:
                    shutil.copyfileobj(response, target)

            retry(download)
            requirements = ROOT / "services/warehouse-service/requirements-flood-gis.txt"
            run([*compose, "run", "-T", "--rm", "--no-deps", "--user", "root",
                 "-v", f"{directory}:/tiles:ro", "-v", f"{requirements}:/tmp/requirements-gis.txt:ro",
                 "warehouse-service", "sh", "-ec",
                 "apt-get update -qq && apt-get install -yqq --no-install-recommends libexpat1 && "
                 "python -m pip install --quiet --target /tmp/flood-gis -r /tmp/requirements-gis.txt && "
                 'PYTHONPATH=/tmp/flood-gis:/app python -m floodinsight_warehouse.flood_data raster "$1" /tiles/source.tif',
                 "flood-raster", name])


def restore(args):
    compose = ["docker", *(["-H", args.docker_host] if args.docker_host else []), "compose"]
    if args.project:
        compose += ["-p", args.project]

    def get(path, query=None):
        return retry(lambda: api(args.api, path, query=query))

    def post(path, body):
        return retry(lambda: api(args.api, path, body=body))

    retry(lambda: run([*compose, "run", "-T", "--rm", "--no-deps", "warehouse-migrate"]))
    status = get("system/status")
    if status["status"] != "ok":
        raise RuntimeError(f"Unavailable dependencies: {status['services']}")
    locations = get("locations")
    flood_points = get("flood-risk/locations")
    coordinates = {row["code"]: (row["latitude"], row["longitude"]) for row in locations}
    flood_coordinates = {row["code"]: (row["latitude"], row["longitude"]) for row in flood_points}
    if not POINTS <= coordinates.keys() or coordinates != flood_coordinates:
        raise RuntimeError("Canonical sampling points disagree across the warehouse and flood API")
    log("locations", [row["code"] for row in flood_points])

    now = datetime.now(timezone.utc)
    coverage = get("flood-data/coverage")
    issue = now.replace(minute=0, second=0, microsecond=0)
    forecasts = {row["point"] for row in coverage["weather_provider_grids"] if row["feed"] == "forecast"
                 and datetime.fromisoformat(row["last_valid"]) >= issue + timedelta(hours=25)}
    last_run = get("weather/ingestion/status").get("latest_run") or {}
    fresh = (last_run.get("status") == "succeeded"
             and datetime.fromisoformat(last_run["finished_at"]) >= now - timedelta(minutes=30))
    if args.refresh_weather or not (fresh and POINTS <= forecasts):
        def ingest_weather():
            result = api(args.api, "weather/ingestion/run", body={})
            log("weather collection", result)
            if result["status"] != "succeeded":
                raise URLError(result.get("error_message") or result["status"])

        retry(ingest_weather)
    else:
        log("weather checkpoint", sorted(forecasts))
    if not POINTS <= {row["location_code"] for row in get("weather/latest")}:
        raise RuntimeError("Current weather snapshots missing for at least one canonical point")

    latest = now.date() - timedelta(days=6)
    windows = [span(date(2022, 10, 14), date(2022, 10, 15)),
               span(args.start, args.end), span(latest - timedelta(days=29), latest)]
    for window in windows:
        for operation in ("backfill", "etl/run"):
            retry(lambda: process(args.api, window, operation))
    coverage = get("flood-data/coverage")
    if not POINTS <= {row["location"] for row in coverage["weather_daily"]}:
        raise RuntimeError("Daily rainfall coverage missing for at least one canonical point")
    log("daily rainfall coverage", coverage["weather_daily"])

    adapters = {}
    if not coverage["events"]:
        adapters["official-events"] = ()
    if not POINTS <= {row["point"] for row in coverage["terrain"] if row["source"] == "open-meteo-cop-dem-glo90"}:
        adapters["elevation"] = ()
    if not any(row["source"] == "open-meteo-marine" and
               datetime.fromisoformat(row["last_valid"]).date() >= now.date() for row in coverage["hydrology"]):
        adapters["coastal-sea-level"] = ()
    failures = []
    for dataset, options in adapters.items():
        try:
            retry(lambda: command(compose, "floodinsight_warehouse.flood_data", "ingest", dataset, *options),
                  attempts=2)
        except subprocess.CalledProcessError:
            failures.append(dataset)
    for day in (date(2023, 10, 13), now.date() - timedelta(days=7)):
        stations = {row["station_key"] for row in coverage["hydrology"]
                    if str(day) in row.get("complete_utc_dates", [])}
        if not POINTS <= stations:
            try:
                retry(lambda: command(compose, "floodinsight_warehouse.flood_data", "ingest", "soil-moisture",
                                      "--start", str(day), "--end", str(day)), attempts=2)
            except subprocess.CalledProcessError:
                failures.append(f"soil-moisture {day}")
    if not args.skip_rasters:
        try:
            import_rasters(compose, coverage)
        except (URLError, TimeoutError, subprocess.CalledProcessError) as error:
            failures.append(f"terrain raster collection: {error}")

    now = datetime.now(timezone.utc)
    issue = now.replace(minute=0, second=0, microsecond=0).isoformat()
    features = json.loads(command(compose, "floodinsight_warehouse.flood_dataset",
                                  "--start", issue, "--end", issue, "--as-of", now.isoformat(),
                                  "--report-only", output=True))
    log("features", {"schema": features["schema"], "hash": features["rows_sha256"], "report": features["report"]})
    assessments = post("flood-risk/generate", {"issued_at": issue})
    log("stored risk", [{key: row[key] for key in ("location", "id", "risk_category", "risk_index", "missing_features")}
                        for row in assessments])
    if not POINTS <= {row["point"]["code"] for row in get("flood-risk/latest") if row["assessment"]}:
        raise RuntimeError("Persisted risk assessments missing for at least one canonical point")

    readiness = get("flood-predictions/readiness")
    metrics = get("flood-predictions/metrics")
    log("training readiness", readiness)
    if args.study and readiness["status"] != "insufficient_training_data" and not metrics["version"]:
        # Train only from an explicit study; do not retry a training request after timeout.
        log("training", api(args.api, "flood-predictions/train",
                            body={"study": json.loads(args.study.read_text(encoding="utf-8"))}))
    if metrics["status"] == "approved":
        for point in flood_points:
            log("inference", post("flood-predictions/predict", {"location": point["code"], "issued_at": issue}))
    log("persisted probabilities", len(get("flood-predictions/results", {"current": "true", "limit": 250})))
    log("coverage", get("flood-data/coverage")["counts"])
    if failures:
        raise RuntimeError(f"Recovery completed with unavailable sources: {', '.join(failures)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--project")
    parser.add_argument("--docker-host")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 6, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 2, 29))
    parser.add_argument("--refresh-weather", action="store_true")
    parser.add_argument("--skip-rasters", action="store_true")
    parser.add_argument("--study", type=Path)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must be on or before --end")
    restore(args)


if __name__ == "__main__":
    main()
