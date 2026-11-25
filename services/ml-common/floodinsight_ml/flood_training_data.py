"""Warehouse evidence, fixed partitions and data gates for urban flood models."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import math

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .flood_features import TARGET, make_row, validate_holdout
from .flood_store import ERA5, FORECAST, postgres_read

TARGET_VERSION = "urban-inundation-within-50m-next-24h-v1"
FEATURES = ("forecast_rain_next_24h_mm", "rain_prev_24h_mm", "rain_max_hour_prev_24h_mm",
            "elevation_m", "built_up_fraction")
ROLES = ("fit", "calibration", "selection", "test")
MIN_EPISODES = {"fit": 20, "calibration": 10, "selection": 10, "test": 10}
MIN_DRY_DAYS = {"fit": 60, "calibration": 30, "selection": 30, "test": 30}
MIN_SPAN = timedelta(days=60)


class TrainingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime
    as_of: AwareDatetime
    cutoffs: tuple[AwareDatetime, AwareDatetime, AwareDatetime]
    locations: dict[str, list[str]]
    surveillance_reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_design(self):
        dates = (self.start, *self.cutoffs, self.end)
        if any((t.astimezone(timezone.utc).hour, t.minute, t.second, t.microsecond) != (0, 0, 0, 0)
               for t in dates):
            raise ValueError("Specify whole UTC days at 00:00 for the study window and cutoffs")
        if (any(end - start < MIN_SPAN for start, end in zip(dates, dates[1:]))
                or self.end - self.start > timedelta(days=5 * 366)
                or not self.end <= self.as_of <= datetime.now(timezone.utc)):
            raise ValueError("Use ordered intervals of at least 60 days, up to five years overall, with a valid as-of")
        if set(self.locations) != set(ROLES) or any(not self.locations[role] for role in ROLES):
            raise ValueError("Pre-register points for all four partitions")
        codes = [point for code in self.locations.values() for point in code]
        if len(codes) != len(set(codes)):
            raise ValueError("A monitoring point cannot belong to multiple partitions or repeat in one")
        if not self.surveillance_reference.strip():
            raise ValueError("Document a reviewed surveillance sampling frame")
        return self


def inventory(conn):
    result = conn.execute("""
        SELECT
          (SELECT count(*) FROM flood_events) AS documented_events,
          (SELECT count(*) FROM flood_observations WHERE label = 'flood_confirmed'
             AND quality IN ('high', 'medium') AND event_id IS NOT NULL AND location_id IS NOT NULL)
             AS candidate_positive_observations,
          (SELECT count(DISTINCT e.event_key) FROM flood_observations o
             JOIN flood_events e ON e.id = o.event_id WHERE o.label = 'flood_confirmed'
             AND o.quality IN ('high', 'medium') AND o.location_id IS NOT NULL) AS candidate_linked_event_keys,
          (SELECT count(*) FROM flood_observations WHERE label = 'non_flood_confirmed'
             AND quality IN ('high', 'medium') AND location_id IS NOT NULL
             AND coverage_start IS NOT NULL AND coverage_end - coverage_start >= interval '24 hours'
             AND coverage_radius_m >= 50) AS candidate_dry_observations,
          (SELECT count(*) FROM raw_weather_forecasts r JOIN data_sources d ON d.id = r.source_id
             WHERE d.code = 'open-meteo-forecast-api' AND r.payload->>'kind' = 'hourly') AS forecast_snapshots,
          (SELECT count(*) FROM dim_location) AS monitoring_points,
          (SELECT count(*) FROM model_versions WHERE kind = 'flood') AS flood_registry_rows,
          (SELECT count(*) FROM flood_probability_results) AS flood_probability_rows
    """).fetchone()
    counts = dict(result)
    reasons = [key for key in ("documented_events", "candidate_positive_observations",
                               "candidate_dry_observations", "forecast_snapshots") if counts[key] == 0]
    if counts["candidate_linked_event_keys"] < sum(MIN_EPISODES.values()):
        reasons.append("independent_event_support_below_minimum")
    return {"status": "insufficient_training_data" if reasons else "partition_verification_required",
            "blocking_inventory": reasons, "inventory": counts}


def grid_groups(codes, grids):
    groups = {code: {code} for code in codes}
    for cell in grids:
        members = [point for point in cell["points"] if point in groups]
        if members:
            merged = set().union(*(groups[member] for member in members))
            for point in merged:
                groups[point] = merged
    return sorted({tuple(sorted(group)) for group in groups.values()})


def input_ready(row):
    for name in FEATURES:
        value = row["features"].get(name)
        record = row["provenance"].get(name)
        if (type(value) not in (int, float) or not math.isfinite(value) or not record
                or record["available_at"] > row["issued_at"]):
            return False
    return row["mode"] == "operational"


def weather_grids(row):
    return sorted({tuple(grid) for grid, _ in row["weather_bins"] if grid[0] in (ERA5, FORECAST)})


def event_groups(rows):
    # Coalesce documented aliases and overlapping windows conservatively.
    keys = defaultdict(list)
    for row in rows:
        label = row["label"]
        if label["status"] == "positive":
            for key in label["event_keys"]:
                keys[key].extend(label["event_windows"])
    ordered = sorted((min(win[0] for win in spans), max(win[1] for win in spans), key)
                     for key, spans in keys.items())
    groups = {}
    end = None
    for begin, finish, key in ordered:
        if end is None or begin >= end:
            episode = key
            end = finish
        else:
            end = max(end, finish)
        groups[key] = episode
    return groups


def support(rows):
    return {
        "rows": len(rows),
        "positive": sum(row["label"]["status"] == "positive" for row in rows),
        "negative": sum(row["label"]["status"] == "negative" for row in rows),
        "independent_event_candidates": len(set(event_groups(rows).values())),
        "distinct_dry_utc_days": len({row["issued_at"].date() for row in rows if row["label"]["status"] == "negative"}),
        "locations": sorted({row["location"] for row in rows}),
        "label_quality": dict(Counter(row["label"]["confidence"] for row in rows)),
    }


def partition(rows, groups, spec):
    details = {}
    reasons = []
    locations = {code for role in ROLES for code in spec.locations[role]}
    for group in groups:
        if len(locations.intersection(group)) > 1:
            reasons.append("More than one nominated point belongs to a shared weather-grid group")
            break
    dates = (spec.start, *spec.cutoffs, spec.end)
    parts = {}
    for role, start, end in zip(ROLES, dates, dates[1:]):
        subset = [row for row in rows if row["location"] in spec.locations[role] and start <= row["issued_at"] < end]
        labels = Counter(row["label"]["status"] for row in subset)
        usable = [row for row in subset if row["label"]["status"] in ("positive", "negative")
                  and input_ready(row) and {g[0] for g in weather_grids(row)} == {ERA5, FORECAST}]
        retained = [row for row in usable if role == "test" or max(row["target_end"], row["label"]["available_at"]) < end]
        parts[role] = retained
        item = support(retained) | {"candidate_labels": dict(labels),
                                   "incomplete_labeled": labels["positive"] + labels["negative"] - len(usable),
                                   "purged": len(usable) - len(retained)}
        details[role] = item
        if item["independent_event_candidates"] < MIN_EPISODES[role] or item["distinct_dry_utc_days"] < MIN_DRY_DAYS[role]:
            reasons.append(f"{role} lacks independent positive episodes or reviewed dry days")
        if not retained or max(row["issued_at"] for row in retained) - min(row["issued_at"] for row in retained) < MIN_SPAN:
            reasons.append(f"{role} lacks 60 days of usable observed coverage")
        if set(item["locations"]) != set(spec.locations[role]):
            reasons.append(f"{role} has nominated points without usable evidence")
    for index, later in enumerate(ROLES[1:], 1):
        early = [row for role in ROLES[:index] for row in parts[role]]
        if early and parts[later]:
            try:
                validate_holdout(early, parts[later], groups)
            except ValueError as error:
                reasons.append(f"{later}: {error}")
    return parts, {"status": "insufficient_training_data" if reasons else "eligible_for_development",
                   "blockers": reasons, "partitions": details, "spatial_groups": groups}


def dataset(conn, spec):
    # One fixed daily decision per point. Unknown surveillance hours remain explicit.
    rows = []
    start = spec.start.astimezone(timezone.utc)
    end = spec.end.astimezone(timezone.utc)
    points = spec.locations
    locations = {code for codes in points.values() for code in codes}
    groups = None
    while start < end:
        last = min(end - TARGET, start + 6 * TARGET)
        known, inputs, _, grids = postgres_read(conn, start, last, spec.as_of, include_inventory=groups is None)
        if groups is None:
            groups = grid_groups({point["code"] for point in known}, grids)
        for day in range((last - start).days + 1):
            issue = start + day * TARGET
            for point in known:
                if point["code"] not in locations:
                    continue
                entries = inputs[point["code"]]
                selected = dict(entries) | {"hydrology": entries["hydrology"] + inputs[None]["hydrology"]}
                for key in ("rain", "forecast", "terrain", "observations"):
                    selected.setdefault(key, [])
                rows.append(make_row(point, issue, spec.as_of, "operational", selected))
        start = last + TARGET
    return partition(rows, groups or [], spec)
