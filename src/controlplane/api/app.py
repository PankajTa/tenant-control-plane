"""FastAPI application factory + uniform error handling."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from controlplane.api.context import AppContext, build_context
from controlplane.api.routes import health, router
from controlplane.config import Settings
from controlplane.db import init_schema
from controlplane.errors import DomainError
from controlplane.messaging.publisher import EventPublisher

log = logging.getLogger(__name__)

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def create_app(
    settings: Settings,
    *,
    engine: Engine | None = None,
    publisher: EventPublisher | None = None,
    run_background: bool = True,
) -> FastAPI:
    ctx: AppContext = build_context(
        settings, engine=engine, publisher=publisher, run_background=run_background
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_schema(ctx.engine)
        if ctx.run_background:
            ctx.relay.start()  # also drains tasks left unpublished by a previous crash
            ctx.consumer.start()
        try:
            yield
        finally:
            if ctx.run_background:
                ctx.consumer.stop()
                ctx.relay.stop()
            ctx.engine.dispose()

    app = FastAPI(title="Tenant Control Plane", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.include_router(router)
    app.include_router(health)

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"loc": [str(p) for p in e["loc"]], "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return error_response(422, "validation_error", "request validation failed", {"errors": problems})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return error_response(500, "internal_error", "internal server error")

    return app
