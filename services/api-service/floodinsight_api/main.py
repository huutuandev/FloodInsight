from contextlib import asynccontextmanager
from logging import getLogger
from time import monotonic
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .config import Settings
from .routes.gateway import router as gateway_router
from .routes.health import router as health_router
from .schemas.gateway import ErrorDetail, Failure, Meta
from .services.upstream import UpstreamError, Upstreams, validation_details

logger = getLogger(__name__)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            app.state.upstreams = Upstreams(client, settings)
            yield

    app = FastAPI(title="FloodInsight REST API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def trace(request: Request, call_next):
        request.state.request_id = uuid4().hex
        started = monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        logger.info("gateway request", extra={
            "request_id": request.state.request_id, "method": request.method,
            "route": getattr(route, "path", None), "status_code": response.status_code,
            "duration_ms": round((monotonic() - started) * 1000, 2),
        })
        return response

    def failure(request, status, error):
        meta = Meta(request_id=request.state.request_id)
        return JSONResponse(Failure(error=error, meta=meta).model_dump(mode="json", exclude_none=True),
                            status_code=status, headers={"X-Request-ID": meta.request_id})

    @app.exception_handler(UpstreamError)
    async def upstream_error(request, exc):
        if exc.status >= 500:
            logger.warning("gateway upstream failure", extra={
                "request_id": request.state.request_id, "upstream": exc.error.service,
                "status_code": exc.status, "error_code": exc.error.code,
            })
        return failure(request, exc.status, exc.error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return failure(request, 422, ErrorDetail(
            code="validation_error", message="Invalid request parameters",
            details=validation_details(exc.errors()),
        ))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        response = failure(request, exc.status_code, ErrorDetail(code="http_error", message=str(exc.detail)))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error("gateway unexpected failure", exc_info=exc,
                     extra={"request_id": request.state.request_id})
        return failure(request, 500, ErrorDetail(code="internal_error", message="Unexpected gateway failure"))

    @app.get("/ready", include_in_schema=False)
    async def ready(request: Request):
        report = await request.app.state.upstreams.status(request.state.request_id)
        return JSONResponse({"data": report, "meta": {"request_id": request.state.request_id}},
                            status_code=200 if report["status"] == "ok" else 503)

    app.include_router(health_router)
    app.include_router(gateway_router)
    return app


app = create_app()
