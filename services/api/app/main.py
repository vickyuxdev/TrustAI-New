"""
services/api/app/main.py
TrustAI Analytics API — serves the Next.js dashboard with all analytics data.
Secured via Azure AD JWT tokens validated by shared auth middleware.
"""
import logging
import os

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import agents, alerts, clients, cost, overview, projects, traces

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger("api")

app = FastAPI(
    title="TrustAI Analytics API",
    description="Analytics backend for the TrustAI dashboard",
    version="0.1.0",
    root_path=os.getenv("TRUSTAI_ROOT_PATH", ""),
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://trustai.yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────
API_V1 = "/api/v1"
app.include_router(overview.router,  prefix=API_V1, tags=["overview"])
app.include_router(clients.router,   prefix=API_V1, tags=["clients"])
app.include_router(projects.router,  prefix=API_V1, tags=["projects"])
app.include_router(agents.router,    prefix=API_V1, tags=["agents"])
app.include_router(traces.router,    prefix=API_V1, tags=["traces"])
app.include_router(cost.router,      prefix=API_V1, tags=["cost"])
app.include_router(alerts.router,    prefix=API_V1, tags=["alerts"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "api"}


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled error", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
