import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ingest_multimodel_and_ground_gauges.py"
SPEC = importlib.util.spec_from_file_location("multimodel_import", SCRIPT)
IMPORTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(IMPORTER)


def test_forecast_parser_converts_unix_axis_to_aware_utc(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    payload = {"latitude": 16, "longitude": 108, "utc_offset_seconds": 0,
               "hourly_units": IMPORTER.UNITS, "hourly": {
        "time": [1794978000, 1794981600],
        **{name: [1.0, 2.0] for name in IMPORTER.VARIABLES},
    }}
    monkeypatch.setattr(IMPORTER, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(IMPORTER.json, "load", lambda _response: payload)
    received, hourly, instants, _ = IMPORTER.fetch_forecast(
        "https://example.invalid", {"latitude": 16, "longitude": 108}, "model", 2, 1
    )
    assert received.tzinfo is not None
    assert all(instant.tzinfo is not None and instant.utcoffset().total_seconds() == 0
               for instant in instants)
    assert instants[1] > instants[0]
    assert len(hourly["cape"]) == 2


def test_forecast_parser_rejects_misaligned_variables(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    payload = {"latitude": 16, "longitude": 108, "utc_offset_seconds": 0,
               "hourly_units": IMPORTER.UNITS,
               "hourly": {"time": [1794978000],
                           **{name: [1.0] for name in IMPORTER.VARIABLES}}}
    payload["hourly"]["cape"] = []
    monkeypatch.setattr(IMPORTER, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(IMPORTER.json, "load", lambda _response: payload)
    with pytest.raises(IMPORTER.ImportErrorDetail, match="do not match"):
        IMPORTER.fetch_forecast("https://example.invalid", {"latitude": 16, "longitude": 108},
                                "model", 1, 1)


@pytest.mark.parametrize("field,value", [
    ("precipitation_probability", 101),
    ("precipitation_probability", -1),
    ("cape", -1),
    ("temperature_2m", float("nan")),
])
def test_forecast_parser_rejects_invalid_measurements(monkeypatch, field, value):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    payload = {"latitude": 16, "longitude": 108, "utc_offset_seconds": 0,
               "hourly_units": IMPORTER.UNITS,
               "hourly": {"time": [1794978000],
                          **{name: [1.0] for name in IMPORTER.VARIABLES}}}
    payload["hourly"][field] = [value]
    monkeypatch.setattr(IMPORTER, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(IMPORTER.json, "load", lambda _response: payload)
    with pytest.raises(IMPORTER.ImportErrorDetail):
        IMPORTER.fetch_forecast("https://example.invalid", {"latitude": 16, "longitude": 108},
                                "model", 1, 1)


def test_run_import_rejects_invalid_options_before_database_connection(monkeypatch):
    monkeypatch.setattr(IMPORTER, "create_engine", lambda *_args, **_kwargs: pytest.fail(
        "invalid CLI options must fail before opening a database connection"
    ))
    args = IMPORTER.argparse.Namespace(days=1, retries=0, timeout=1, url=IMPORTER.API_URL)
    with pytest.raises(ValueError, match="--retries must be at least 1"):
        IMPORTER.run_import(args)


def test_importer_does_not_synthesize_gauge_or_issue_timestamps():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "VRAIN_OCT2022_PEAKS" not in source
    assert "weight =" not in source
    assert "slot_issued" not in source
    assert "VALUES (:source, :run, :location, :valid, NULL, :received, :digest, :payload)" in source
