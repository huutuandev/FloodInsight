import hashlib
import os
from pathlib import Path
from uuid import uuid4

import joblib
import psycopg
import sklearn
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SOURCE = "open-meteo-archive-era5"


class DataUnavailable(ValueError):
    pass


class ModelUnavailable(LookupError):
    pass


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")
    host: str = "localhost"
    port: int = 5432
    db: str
    user: str
    password: SecretStr


def connect():
    db = DatabaseSettings()
    return psycopg.connect(
        host=db.host, port=db.port, dbname=db.db, user=db.user,
        password=db.password.get_secret_value(), row_factory=dict_row, connect_timeout=5,
        options="-c timezone=UTC -c statement_timeout=60000",
    )


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Models:
    def __init__(self, kind, name, directory):
        self.kind, self.name = kind, name
        self.directory = Path(directory).resolve()

    def save(self, artifact, metadata):
        self.directory.mkdir(parents=True, exist_ok=True)
        version = uuid4().hex
        name = f"{version}.joblib"
        path = self.directory / name
        temporary = self.directory / f".{name}.tmp"
        try:
            joblib.dump(artifact, temporary, compress=3)
            os.replace(temporary, path)
            metadata = metadata | {"sha256": digest(path), "sklearn_version": sklearn.__version__}
            with connect() as conn:
                row = conn.execute("""
                    INSERT INTO model_versions (kind, model_name, version, artifact_uri, training_metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, version, model_name, kind, created_at, training_metadata
                """, (self.kind, self.name, version, name, Jsonb(metadata))).fetchone()
        finally:
            temporary.unlink(missing_ok=True)
        # Unique filenames also keep a durable artifact if a DB commit outcome is ambiguous.
        return row

    def artifact_path(self, model):
        expected_name = f"{model['version']}.joblib"
        path = self.directory / expected_name
        if (
            model["artifact_uri"] != expected_name or not path.is_file()
            or path.resolve().parent != self.directory
            or model["training_metadata"].get("sklearn_version") != sklearn.__version__
            or digest(path) != model["training_metadata"].get("sha256")
        ):
            raise ModelUnavailable("Registered model artifact is missing, changed, or incompatible")
        return path

    def lookup(self, version, *, required_metadata=None):
        with connect() as conn:
            models = conn.execute("""
                SELECT id, kind, model_name, version, artifact_uri, created_at, training_metadata
                FROM model_versions
                WHERE kind = %s AND model_name = %s AND (%s::text IS NULL OR version = %s)
                  AND training_metadata @> %s
                ORDER BY id DESC
            """, (self.kind, self.name, version, version, Jsonb(required_metadata or {}))).fetchall()
        if not models:
            raise ModelUnavailable("Train or select an existing model version")
        for model in models:
            try:
                self.artifact_path(model)
            except ModelUnavailable:
                if version:
                    raise
            else:
                return model
        raise ModelUnavailable("No registered model has a usable artifact")

    def load(self, version, *, required_metadata=None):
        model = self.lookup(version, required_metadata=required_metadata)
        return model, joblib.load(self.artifact_path(model))
