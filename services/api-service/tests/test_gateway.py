import httpx
from fastapi.testclient import TestClient

from floodinsight_api.main import create_app

DATES = {"start_date": "2023-10-13", "end_date": "2023-10-14"}


def client_for(handler):
    return TestClient(create_app(transport=httpx.MockTransport(handler)))


def test_empty_weather_and_typed_locations():
    def upstream(request):
        assert request.url.host == "warehouse-service"
        assert request.headers["x-request-id"]
        if request.url.path.endswith("/locations"):
            return httpx.Response(200, json={
                "items": [{"code": "hai-chau", "name": "Hải Châu", "latitude": 16.076345,
                           "longitude": 108.221783}], "has_more": False,
            })
        assert request.url.path == "/warehouse/weather/observations"
        assert request.url.params["location"] == "hai-chau"
        return httpx.Response(200, json={"items": [], "has_more": False})

    with client_for(upstream) as client:
        result = client.get("/api/v1/weather", params=DATES | {"location": "hai-chau"})
        assert result.status_code == 200
        assert result.json()["data"] == []
        assert result.json()["meta"]["kind"] == "observed_weather"
        assert result.json()["meta"]["request_id"] == result.headers["x-request-id"]
        assert client.get("/api/v1/locations").json()["data"][0]["code"] == "hai-chau"


def test_invalid_parameters_and_cors():
    def upstream(request):
        raise AssertionError("Invalid or preflight requests should never reach upstreams")

    with client_for(upstream) as client:
        for query in (
            DATES | {"limit": 0},
            {"start_date": "2023-10-14", "end_date": "2023-10-13"},
        ):
            response = client.get("/api/v1/rainfall", params=query)
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "validation_error"
        preflight = client.options("/api/v1/analytics/generate", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        })
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
        schema = client.get("/openapi.json").json()
        assert "requestBody" in schema["paths"]["/api/v1/classifications/train"]["post"]
        assert "/api/v1/system/status" in schema["paths"]


def test_upstream_failures_and_system_health_are_isolated():
    def upstream(request):
        if request.url.path == "/ready":
            return httpx.Response(503, json={"detail": "warehouse database unavailable"})
        if request.url.path == "/health":
            if request.url.host == "analysis-service":
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/warehouse/locations":
            return httpx.Response(503, json={"detail": "private database error"})
        if request.url.path == "/analysis/patterns":
            raise httpx.ConnectError("offline", request=request)
        raise httpx.ReadTimeout("too slow", request=request)

    with client_for(upstream) as client:
        health = client.get("/api/v1/system/status").json()["data"]
        assert health["status"] == "degraded"
        assert health["services"]["postgres"]["status"] == "unavailable"
        assert health["services"]["analytics"]["status"] == "unavailable"
        assert health["services"]["ingestion"]["status"] == "ok"
        assert client.get("/ready").status_code == 503
        invalid = client.get("/api/v1/locations")
        assert invalid.status_code == 503
        assert "private database error" not in invalid.text
        assert client.get("/api/v1/analytics", params=DATES | {"location": "hai-chau"}).status_code == 503
        timeout = client.get("/api/v1/weather/latest")
        assert timeout.status_code == 504
        assert timeout.json()["error"]["service"] == "ingestion"


def test_fixed_dispatch_and_pagination_for_model_routes():
    seen = []

    def upstream(request):
        seen.append((request.url.host, request.url.path))
        if request.url.path == "/prediction/results":
            assert request.url.params["limit"] == "2"
            assert request.url.params["location"] == "hai-chau"
            return httpx.Response(200, json=[{"rainfall_mm": 1.2}, {"rainfall_mm": 3.4}])
        if request.url.path == "/analysis/generate":
            return httpx.Response(200, json=[])
        if request.url.path == "/clustering/run":
            return httpx.Response(404, json={"detail": "Train or select an existing model version"})
        return httpx.Response(200, content=b"invalid")

    with client_for(upstream) as client:
        response = client.get("/api/v1/predictions", params={"limit": 1, "location": "hai-chau"}).json()
        assert response["data"] == [{"rainfall_mm": 1.2}]
        assert response["meta"]["has_more"]
        assert response["meta"]["kind"] == "ml_rainfall_prediction"
        request = DATES | {"location": "hai-chau"}
        assert client.post("/api/v1/analytics/generate", json=request).status_code == 200
        assert client.post("/api/v1/clustering/run", json=request).status_code == 404
        assert client.get("/api/v1/classifications/metrics").status_code == 502
    assert seen == [
        ("prediction-service", "/prediction/results"),
        ("analysis-service", "/analysis/generate"),
        ("clustering-service", "/clustering/run"),
        ("classification-service", "/classification/metrics"),
    ]

