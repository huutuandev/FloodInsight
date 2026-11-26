"""Export a flood feature dataset and quality report from a read-only snapshot."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import statistics

from sqlalchemy import create_engine, text

from floodinsight_ml.availability import ERA5_DELAY
from floodinsight_ml.flood_features import HOUR, RADIUS_M, SCHEMA, VERSION, WET_MM, make_row

from floodinsight_ml.flood_store import QUERIES, read as read_features

from .config import DatabaseSettings

def read(conn, start, end, as_of):
    return read_features(lambda sql, params: conn.execute(text(sql), params).mappings(), start, end, as_of)


def encode(value):
    return json.dumps(value, default=lambda v: v.isoformat(), ensure_ascii=True, allow_nan=False, sort_keys=True)


def spatial_groups(codes, grids):
    groups = {code: {code} for code in codes}
    for cell in grids:
        members = [point for point in cell["points"] if point in groups]
        if members:
            combined = set().union(*(groups[member] for member in members))
            for point in combined:
                groups[point] = combined
    return sorted({tuple(sorted(group)) for group in groups.values()})


def episode_count(evidence, event_keys):
    keyed = {}
    for row in evidence:
        key = row["event_key"]
        if key in event_keys:
            lower, upper = keyed.get(key, (row["event_start"], row["event_end"]))
            keyed[key] = (min(lower, row["event_start"]), max(upper, row["event_end"]))
    spans = sorted(keyed.values())
    count, end = 0, None
    for lower, upper in spans:
        if end is None or lower >= end:
            count += 1
        end = upper if end is None else max(end, upper)
    return count


def quality(rows, evidence, grids):
    labels = Counter(row["label"]["status"] for row in rows)
    event_keys = {key for row in rows if row["label"]["status"] == "positive" for key in row["label"]["event_keys"]}
    feature_stats = {}
    issue_gaps = Counter()
    weather_bins = defaultdict(set)
    for row in rows:
        for bin_key in row["weather_bins"]:
            weather_bins[bin_key].add(row["location"])
        for feature, source in row["provenance"].items():
            if source["available_at"] > row["issued_at"]:
                raise ValueError(f"Predictor {feature} is only available after issuance")
        if set(row["provenance"]) != {name for name, value in row["features"].items() if value is not None}:
            raise ValueError("Non-null feature has missing provenance")
        issue_gaps[row["label"].get("reason", row["label"]["status"])] += 1
    for name in SCHEMA:
        values = [row["features"][name] for row in rows if row["features"][name] is not None]
        if name == "land_cover_class":
            distribution = dict(Counter(values))
        else:
            distribution = (dict(min=min(values), median=statistics.median(values), max=max(values),
                                 mean=statistics.fmean(values)) if values else None)
        feature_stats[name] = dict(unit=SCHEMA[name], available_at_issuance=len(values),
                                   missing_percent=100 * (len(rows) - len(values)) / len(rows) if rows else None,
                                   distribution=distribution)
    identity = {(row["location"], row["issued_at"]) for row in rows}
    if len(identity) != len(rows):
        raise ValueError("Duplicate point-issuance output")
    codes = sorted({row["location"] for row in rows})
    observed = [(r["location_id"], r["observed_at"], r["latitude"], r["longitude"], r["label"]) for r in evidence]
    return dict(
        rows=len(rows), locations=codes, first_issue=min((row["issued_at"] for row in rows), default=None),
        last_issue=max((row["issued_at"] for row in rows), default=None),
        labels={status: labels[status] for status in ("positive", "negative", "unknown")},
        label_reasons=dict(issue_gaps), labeled_positive_fraction=(labels["positive"] /
            (labels["positive"] + labels["negative"]) if labels["positive"] + labels["negative"] else None),
        independent_event_candidates=episode_count(evidence, event_keys), positive_event_keys=sorted(event_keys),
        duplicate_observation_candidates=len(observed) - len(set(observed)),
        feature_statistics=feature_stats, inventory_grids=grids, spatial_holdout_groups=spatial_groups(codes, grids),
        used_distinct_grid_valid_times=len(weather_bins),
        used_shared_grid_valid_times=sum(len(points) > 1 for points in weather_bins.values()),
        readiness="blocked_missing_label_classes" if not labels["positive"] or not labels["negative"]
        else "requires_independent_event_and_spatial_review",
    )


def build(conn, start, end, as_of, mode):
    points, inputs, evidence, grids = read(conn, start, end, as_of)
    rows = []
    for step in range((end - start) // HOUR + 1):
        issuance = start + step * HOUR
        for point in points:
            source = inputs[point["code"]]
            point_inputs = {name: source[name] for name in QUERIES}
            point_inputs["hydrology"] = source["hydrology"] + inputs[None]["hydrology"]
            rows.append(make_row(point, issuance, as_of, mode, point_inputs))
    return dict(schema=VERSION, feature_units=SCHEMA, mode=mode, label_as_of=as_of,
                availability_basis=("recorded_receipts" if mode == "operational"
                                    else "assumed_era5_delay_recorded_other_receipts"),
                settings=dict(start=start, end=end, target_hours=24, point_radius_m=RADIUS_M,
                              wet_hour_mm=WET_MM, assumed_era5_delay_hours=ERA5_DELAY // HOUR),
                report=quality(rows, evidence, grids),
                rows_sha256=sha256(encode(rows).encode()).hexdigest(), rows=rows)


def timestamp(text_value):
    try:
        value = datetime.fromisoformat(text_value)
        if value.utcoffset() is None:
            raise ValueError
        return value.astimezone(timezone.utc)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected ISO 8601 with a UTC offset") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--as-of", type=timestamp, required=True)
    parser.add_argument("--mode", choices=("operational", "retrospective"), default="operational")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if not timedelta(0) <= args.end - args.start <= timedelta(days=7):
        parser.error("Use an ordered issuance window of at most seven days")
    if any((x.minute, x.second, x.microsecond) != (0, 0, 0) for x in (args.start, args.end)):
        parser.error("Issuance must be on whole UTC hours")
    if not args.end <= args.as_of <= datetime.now(timezone.utc):
        parser.error("As-of time must be between the last issuance and now")
    engine = create_engine(DatabaseSettings().url(), connect_args={"connect_timeout": 5})
    with engine.begin() as conn:
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '60s'"))
        dataset = build(conn, args.start, args.end, args.as_of, args.mode)
    if args.report_only:
        del dataset["rows"]
    print(encode(dataset))


if __name__ == "__main__":
    main()
