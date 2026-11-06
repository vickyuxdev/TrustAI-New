"""
services/admin/app/main.py
TrustAI Admin Service — client/project onboarding, API key management,
model pricing, connector configuration, and user management.
All routes require Azure AD authentication + appropriate RBAC roles.
"""
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from app.routers import api_keys, clients, connectors, internal, pricing, projects

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

app = FastAPI(
    title="TrustAI Admin Service",
    description="Client/project management and platform configuration for TrustAI",
    version="0.1.0",
    root_path=os.getenv("TRUSTAI_ROOT_PATH", ""),
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://trustai.yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.middleware("http")
async def secure_headers(request: Request, call_next):
    """OWASP secure-headers baseline for a JSON API."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


API_V1 = "/api/v1"
app.include_router(clients.router,    prefix=API_V1, tags=["clients"])
app.include_router(projects.router,   prefix=API_V1, tags=["projects"])
app.include_router(api_keys.router,   prefix=API_V1, tags=["api-keys"])
app.include_router(pricing.router,    prefix=API_V1, tags=["pricing"])
app.include_router(connectors.router, prefix=API_V1, tags=["connectors"])
app.include_router(internal.router,   prefix=API_V1, tags=["internal"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "admin"}
