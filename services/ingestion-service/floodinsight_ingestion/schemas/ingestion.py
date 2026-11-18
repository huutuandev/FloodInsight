import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Trigger = Literal["manual", "scheduled"]


class RunSummary(BaseModel):
    id: int
    run_key: str
    trigger: Trigger | None
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    records_inserted: int | None
    error_message: str | None


class IngestionStatus(BaseModel):
    scheduler_enabled: bool
    interval_seconds: int
    next_run_at: datetime | None
    latest_run: RunSummary | None


class LatestSnapshot(BaseModel):
    location_code: str
    valid_at: datetime
    issued_at: datetime | None
    received_at: datetime
    payload: dict


@dataclass(frozen=True)
class Snapshot:
    location_code: str
    valid_at: datetime
    received_at: datetime
    payload: dict

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()
