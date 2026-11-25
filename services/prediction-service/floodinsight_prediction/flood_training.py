"""Operator entry point for flood readiness, candidate training and review."""

import argparse
from pathlib import Path
import json
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from floodinsight_ml.flood_features import VERSION
from floodinsight_ml.flood_models import POLICY_VERSION, development
from floodinsight_ml.flood_risk import digest
from floodinsight_ml.flood_training_data import FEATURES, TARGET_VERSION, TrainingSpec, dataset, inventory
from floodinsight_ml.storage import ModelUnavailable, Models, connect

from .config import Settings

REGISTRY_KIND = "flood"
REGISTRY_NAME = "urban-inundation-next-24h"
SERVABLE = {
    "feature_version": VERSION, "target_version": TARGET_VERSION,
    "policy_version": POLICY_VERSION, "release_status": "approved", "features": list(FEATURES),
}


def registry(settings):
    return Models(REGISTRY_KIND, REGISTRY_NAME, Path(settings.artifact_dir) / "flood")


def readiness():
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return inventory(conn)


def dataset_digest(parts):
    body = json.loads(json.dumps(parts, sort_keys=True, default=lambda v: v.isoformat(), allow_nan=False))
    return digest(body)


def train(study_path, settings, *, study=None):
    with connect() as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(12870534) AS acquired").fetchone()["acquired"]:
            return {"status": "training_in_progress"}
        return train_candidate(study_path, settings, study)


def train_candidate(study_path, settings, study):
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        report = inventory(conn)
        if report["status"] == "insufficient_training_data":
            return report
        if study_path is None and study is None:
            return report | {"status": "study_design_required"}
        spec = study or TrainingSpec.model_validate_json(study_path.read_text(encoding="utf-8-sig"))
        parts, partition_report = dataset(conn, spec)
    if partition_report["status"] != "eligible_for_development":
        return report | partition_report
    artifact, assessment = development(parts)
    result = report | partition_report | {"evaluation": assessment, "status": assessment["status"]}
    if artifact is None:
        return result
    evaluation_hash = digest(assessment)
    metadata = SERVABLE | {
        "release_status": "review_required", "study": spec.model_dump(mode="json"),
        "dataset_sha256": dataset_digest(parts), "partition_report": partition_report,
        "evaluation": assessment, "evaluation_sha256": evaluation_hash,
        "validated_locations": assessment["validated_locations"], "threshold": assessment["threshold"],
        "calibration": assessment["calibration"],
    }
    artifact |= {"feature_version": VERSION, "target_version": TARGET_VERSION,
                 "evaluation_sha256": evaluation_hash}
    candidate = registry(settings).save(artifact, metadata)
    return result | {"candidate_version": candidate["version"], "evaluation_sha256": evaluation_hash}


class ReleaseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_reference: str = Field(min_length=1, max_length=1000)
    surveillance_reference: str = Field(min_length=1, max_length=1000)
    evaluation_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    surveillance_and_calibration_reviewed: Literal[True]


def publish(version, review_path, settings):
    review = ReleaseReview.model_validate_json(review_path.read_text(encoding="utf-8-sig"))
    if not review.review_reference.strip():
        raise ValueError("A traceable review reference is required")
    candidate = registry(settings).lookup(version, required_metadata=SERVABLE | {"release_status": "review_required"})
    meta = candidate["training_metadata"]
    if (meta["evaluation"]["status"] != "eligible_for_release_review"
            or meta["evaluation_sha256"] != review.evaluation_sha256
            or digest(meta["evaluation"]) != review.evaluation_sha256
            or meta["study"]["surveillance_reference"] != review.surveillance_reference
            or not meta["validated_locations"]):
        raise ValueError("Review does not match the independently evaluated candidate")
    release = Jsonb({"release_status": "approved", "release_review": review.model_dump(mode="json")})
    with connect() as conn:
        row = conn.execute("""
            UPDATE model_versions SET training_metadata = training_metadata || %s
                || jsonb_build_object('release_approved_at', clock_timestamp())
            WHERE id = %s AND kind = 'flood' AND training_metadata = %s
            RETURNING version
        """, (release, candidate["id"], Jsonb(meta))).fetchone()
        if row is None:
            raise ModelUnavailable("Candidate changed after review began")
    return {"status": "approved", "version": row["version"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("readiness")
    training = commands.add_parser("train")
    training.add_argument("--study", type=Path)
    release = commands.add_parser("publish")
    release.add_argument("version")
    release.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "readiness":
        result = readiness()
    elif args.command == "train":
        result = train(args.study, Settings())
    else:
        result = publish(args.version, args.review, Settings())
    print(json.dumps(result, indent=2, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
