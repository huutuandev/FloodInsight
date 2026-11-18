"""Explicit recovery via the existing gateway. Run once at a time."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SOURCE = "open-meteo-archive-era5"
VIETNAM = timezone(timedelta(hours=7))


class APIError(RuntimeError):
    def __init__(self, status, message, body):
        self.status = status
        self.body = body
        super().__init__(message)


def api(base, path, query=None, body=None):
    url = f"{base.rstrip('/')}/api/v1/{path}"
    if query:
        url += "?" + urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=190 if data is not None else 20) as response:
            return json.load(response)["data"]
    except HTTPError as error:
        payload = json.load(error).get("error", {})
        raise APIError(error.code, f"{path}: HTTP {error.code}: {payload}", payload) from error


def span(start, end):
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def process(base, window, operation):
    while True:
        run = api(base, f"weather/{operation}", body=window | {"max_batches": 5})
        progress = run["progress"]
        print(operation, run["id"], run["status"], progress, flush=True)
        if run["status"] != "succeeded":
            raise RuntimeError(run["error_message"] or f"{operation} failed")
        if not progress["remaining_batches"]:
            return
        if not progress["batches_processed"]:
            raise RuntimeError(f"{operation} did not advance its checkpoint")


def metadata(base, group, window):
    try:
        return api(base, f"{group}/metrics")
    except APIError as error:
        if error.status != 404 or error.body.get("message") not in {
            "Train or select an existing model version", "No registered model has a usable artifact",
        }:
            raise
    payload = window if group == "clustering" else window | {"availability": "retrospective"}
    registered = api(base, f"{group}/train", body=payload)
    print("registered", group, registered["version"], flush=True)
    return api(base, f"{group}/metrics", {"version": registered["version"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--phase", choices=["data", "outputs", "all"], default="all")
    args = parser.parse_args()
    base = args.api
    if api(base, "system/status")["status"] != "ok":
        raise RuntimeError("Fix unavailable dependencies before recovery")
    historical = span(args.start, args.end)
    latest = datetime.now(timezone.utc).date() - timedelta(days=6)
    recent = span(latest - timedelta(days=29), latest)
    if args.phase in ("data", "all"):
        for window in (historical, recent):
            process(base, window, "backfill")
            process(base, window, "etl/run")
    if args.phase == "data":
        return

    points = api(base, "locations")
    if not points:
        raise RuntimeError("The warehouse location dimension is empty; run the data phase")
    for point in points:
        code = point["code"]
        for window in (historical, recent):
            scope = window | {"location": code, "source": SOURCE}
            if not api(base, "rainfall/daily", scope | {"limit": 1}):
                raise RuntimeError(f"No historical rainfall for {code} in {window}")
            saved = api(base, "analytics", scope)
            if len(saved) != 10:
                saved = api(base, "analytics/generate", body=scope)
            print("patterns", code, window, len(saved), flush=True)

    model = metadata(base, "clustering", historical)
    for window in (historical, recent):
        result = api(base, "clustering/run", body=window | {"version": model["version"]})
        print("clusters", result["stored_rows"], flush=True)
    target = (datetime.now(VIETNAM).date() + timedelta(days=1)).isoformat()
    for group in ("predictions", "classifications"):
        model = metadata(base, group, historical)
        for code in model.get("locations", []):
            query = {"version": model["version"], "location": code, "start_date": target, "end_date": target}
            if not api(base, f"{group}/results", query):
                prediction = api(base, f"{group}/predict", body={"version": model["version"], "location": code})
                print(group, prediction, flush=True)
        print(group, "metrics", model["metrics"], flush=True)


if __name__ == "__main__":
    main()

