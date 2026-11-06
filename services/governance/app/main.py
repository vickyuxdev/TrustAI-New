"""
services/governance/app/main.py
TrustAI Governance Service (FastAPI :8000 in the container, :8004 on the host).

Startup creates the governance tables (when enabled) and seeds the system guardrail/policy catalog.
"""
from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.responses import Response

from app import __version__
from app.config import get_settings
from app.db import create_tables, get_sessionmaker, reset_engine
from app.routers import agents, evaluations, guardrails, platform, risk
from app.security import SecurityHeadersMiddleware
from app.services.catalog import seed_catalog
from app.services.evaluations import wait_inline

structlog.configure(
    processors=[structlog.stdlib.add_log_level, structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer()],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = logging.getLogger("governance")


async def init_storage() -> None:
    """Create tables (if configured) and seed the system catalog."""
    if get_settings().create_tables_on_startup:
        await create_tables()
    async with get_sessionmaker()() as session:
        await seed_catalog(session)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare storage on start; finish in-process evaluations and close the pool on stop."""
    logging.basicConfig(level=get_settings().log_level)
    await init_storage()
    yield
    try:
        await wait_inline(timeout=30)
    except TimeoutError:
        logger.warning("in-process evaluations still running at shutdown")
    await reset_engine()


def create_app() -> FastAPI:
    """Application factory (tests build a fresh app per test)."""
    settings = get_settings()
    app = FastAPI(
        title="TrustAI Governance Service",
        description="Agent registry & onboarding, risk assessment, guardrails & policies, red-team evaluations, "
                    "AI-gateway control and evidence for RandomTrees TrustAI.",
        version=__version__,
        root_path=os.getenv("TRUSTAI_ROOT_PATH", ""),
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o).rstrip("/") for o in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Propagate or create X-Request-ID for log correlation."""
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 with field errors (input values are not echoed back)."""
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Never leak internals; log with the request id."""
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    api = "/api/v1"
    app.include_router(agents.router, prefix=api, tags=["agents"])
    app.include_router(risk.router, prefix=api, tags=["risk"])
    app.include_router(guardrails.router, prefix=api, tags=["guardrails & policies"])
    app.include_router(evaluations.router, prefix=api, tags=["evaluations"])
    app.include_router(platform.router, prefix=api, tags=["gateway & events"])

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, Any]:
        """Liveness."""
        return {"status": "ok", "service": "governance", "version": __version__}

    @app.get("/ready", tags=["health"])
    async def ready() -> JSONResponse:
        """Readiness: database reachable."""
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "unavailable", "error": type(exc).__name__})
        from app.engine import backends

        return JSONResponse(content={"status": "ready", "backends": {
            "azure_content_safety": backends.content_safety_enabled(), "llm_judge": backends.judge_enabled(),
            "eval_executor": get_settings().eval_executor}})

    return app


app = create_app()
