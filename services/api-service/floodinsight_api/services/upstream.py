import asyncio

import httpx

from ..schemas.gateway import ErrorDetail


class UpstreamError(Exception):
    def __init__(self, status, code, message, service, details=None):
        self.status = status
        self.error = ErrorDetail(code=code, message=message, service=service, details=details)


def validation_details(errors):
    return [
        {"field": ".".join(str(part) for part in row.get("loc", [])), "message": str(row.get("msg", ""))}
        for row in errors if isinstance(row, dict)
    ]


def reject_constant(value):
    raise ValueError("Non-finite number in upstream JSON")


class Upstreams:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings
        self.urls = settings.upstreams

    async def call(self, request_id, service, path, *, params=None, body=None, method="GET"):
        timeout = self.settings.processing_timeout if method == "POST" else self.settings.read_timeout
        try:
            response = await self.client.request(
                method, self.urls[service] + path, params=params, json=body,
                headers={"X-Request-ID": request_id}, timeout=httpx.Timeout(timeout, connect=min(3, timeout)),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(504, "upstream_timeout", "Service request timed out", service) from exc
        except httpx.RequestError as exc:
            raise UpstreamError(503, "service_unavailable", "Service could not be reached", service) from exc
        try:
            data = response.json(parse_constant=reject_constant)
        except ValueError:
            data = None
        status = response.status_code
        if 200 <= status < 300 and isinstance(data, (dict, list)):
            return data
        if status in (400, 404, 409, 422, 429):
            detail = data.get("detail") if isinstance(data, dict) else None
            raise UpstreamError(
                status, "upstream_rejected",
                detail if isinstance(detail, str) else "Service rejected the request",
                service, validation_details(detail) if isinstance(detail, list) else None,
            )
        if status == 503:
            raise UpstreamError(503, "service_unavailable", "Service or its database is unavailable", service)
        if status == 504:
            raise UpstreamError(504, "upstream_timeout", "Service request timed out", service)
        detail = data.get("detail") if isinstance(data, dict) else None
        if service == "ingestion" and status == 502 and isinstance(detail, dict) and isinstance(detail.get("id"), int):
            raise UpstreamError(502, "ingestion_failed", "Ingestion failed; see ingestion history", service,
                                [{"field": "run_id", "message": str(detail["id"])}])
        raise UpstreamError(502, "bad_gateway", "Service returned an invalid or failed response", service)

    async def status(self, request_id):
        async def probe(name, service, path):
            try:
                async with asyncio.timeout(self.settings.probe_timeout):
                    response = await self.client.get(
                        self.urls[service] + path, headers={"X-Request-ID": request_id},
                    )
                    payload = response.json(parse_constant=reject_constant)
                    ready = response.is_success and isinstance(payload, dict) and payload.get("status") == "ok"
                    return name, {"status": "ok" if ready else "unavailable", "http_status": response.status_code}
            except (TimeoutError, httpx.RequestError, ValueError):
                return name, {"status": "unavailable", "http_status": None}
        probes = [(name, name, "/health") for name in self.urls]
        checks = dict(await asyncio.gather(*(probe(*item) for item in probes), probe("postgres", "warehouse", "/ready")))
        return {"status": "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded",
                "services": {"gateway": {"status": "ok", "http_status": 200}, **checks}}

