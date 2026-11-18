"""Shared registry behavior used by all three model APIs."""
from contextlib import contextmanager

import joblib
import pytest
import sklearn

from floodinsight_ml import storage


def test_registry_skips_broken_latest_but_rejects_explicit_broken_version(tmp_path, monkeypatch):
    valid = tmp_path / "available.joblib"
    joblib.dump({"fitted": True}, valid)
    rows = [
        {"version": "missing", "artifact_uri": "missing.joblib", "training_metadata": {}},
        {"version": "available", "artifact_uri": valid.name,
         "training_metadata": {"sklearn_version": sklearn.__version__, "sha256": storage.digest(valid)}},
    ]

    class Connection:
        def execute(self, _sql, params):
            self.version = params[-1]
            return self

        def fetchall(self):
            return [row for row in rows if self.version is None or row["version"] == self.version]

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(storage, "connect", connect)
    registry = storage.Models("clustering", "test", tmp_path)
    model, artifact = registry.load(None)
    assert model["version"] == "available"
    assert artifact["fitted"]
    with pytest.raises(storage.ModelUnavailable, match="artifact"):
        registry.lookup("missing")

