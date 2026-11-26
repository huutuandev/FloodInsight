import asyncio
import json
from pathlib import Path

import httpx
import pytest

from floodinsight_ingestion.config import Settings
from floodinsight_ingestion.services import open_meteo

FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_hai_chau.json"


def test_provider_retries_and_validates_recorded_response(monkeypatch):
    point = open_meteo.DANANG_POINTS[0]
    monkeypatch.setattr(open_meteo, "DANANG_POINTS", (point,))
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=FIXTURE.read_bytes())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await open_meteo.OpenMeteoClient(http, Settings(past_hours=0, forecast_hours=2)).fetch()

    snapshots = asyncio.run(run())
    assert len(requests) == 2
    params = requests[-1].url.params
    assert params["timezone"] == "GMT"
    assert params["timeformat"] == "unixtime"
    assert params["latitude"] == str(point.latitude)
    assert [row.payload["kind"] for row in snapshots] == ["current", "hourly", "hourly"]
    assert snapshots[0].valid_at.timestamp() == 1794977100
    assert snapshots[0].payload["values"]["relative_humidity_2m"] == 75
    assert snapshots[0].payload["interval_seconds"] == 900
    assert len({row.digest for row in snapshots}) == 3


def test_provider_rejects_malformed_hourly_series(monkeypatch):
    monkeypatch.setattr(open_meteo, "DANANG_POINTS", open_meteo.DANANG_POINTS[:1])
    payload = json.loads(FIXTURE.read_bytes())
    payload["hourly"]["precipitation"].pop()

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as http:
            await open_meteo.OpenMeteoClient(http, Settings(past_hours=0, forecast_hours=2)).fetch()

    with pytest.raises(open_meteo.ProviderError, match="invalid Open-Meteo response"):
        asyncio.run(run())


def test_provider_bounds_request_duration(monkeypatch):
    monkeypatch.setattr(open_meteo, "DANANG_POINTS", open_meteo.DANANG_POINTS[:1])

    async def delayed_response(request):
        await asyncio.sleep(10)

    async def run():
        transport = httpx.MockTransport(delayed_response)
        async with httpx.AsyncClient(transport=transport) as http:
            settings = Settings(past_hours=0, forecast_hours=2, timeout_seconds=0.02, max_attempts=1)
            await open_meteo.OpenMeteoClient(http, settings).fetch()

    with pytest.raises(open_meteo.ProviderError, match="timed out"):
        asyncio.run(run())
