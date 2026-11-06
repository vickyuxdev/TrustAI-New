"""
services/ingestion/app/main.py
TrustAI Ingestion Service — receives telemetry from the SDK,
validates API keys, enforces rate limits, and enqueues to Event Hub.
"""
import logging
import os
import time

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import traces
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger("ingestion")

app = FastAPI(
    title="TrustAI Ingestion Service",
    description="Receives GenAI telemetry from the TrustAI SDK",
    version="0.1.0",
    root_path=os.getenv("TRUSTAI_ROOT_PATH", ""),
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # SDK calls from any origin; auth is via API key
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(traces.router, prefix="/v1", tags=["traces"])


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "ingestion", "version": "0.1.0"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
