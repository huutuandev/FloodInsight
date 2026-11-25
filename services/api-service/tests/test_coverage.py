import httpx
from fastapi.testclient import TestClient

from floodinsight_api.main import create_app


def test_rainfall_coverage_uses_the_warehouse_and_preserves_errors():
    def upstream(request):
        assert request.url.host == "warehouse-service"
        assert request.url.path == "/warehouse/rainfall/coverage"
        assert request.url.params["source"] == "open-meteo-archive-era5"
        if request.url.params.get("location") == "failure":
            return httpx.Response(503, json={"detail": "database unavailable"})
        return httpx.Response(200, json={"has_more": False, "items": [{
            "location": "hai-chau", "source": "open-meteo-archive-era5",
            "first_date": "2023-06-01", "last_date": "2023-06-02", "days_with_rainfall": 2,
        }]})

    with TestClient(create_app(transport=httpx.MockTransport(upstream))) as client:
        response = client.get("/api/v1/rainfall/coverage")
        assert response.status_code == 200
        assert response.json()["data"][0]["last_date"] == "2023-06-02"
        failed = client.get("/api/v1/rainfall/coverage", params={"location": "failure"})
        assert failed.status_code == 503
        assert failed.json()["error"]["service"] == "warehouse"

