"""
services/ingestion/app/middleware.py
Request logging and rate-limit middleware for the Ingestion Service.
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ingestion.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            "%s %s → %s (%sms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware placeholder.
    Primary rate limiting is enforced per-API-key in dependencies.py.
    This middleware can add global IP-based limits if needed.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        return await call_next(request)
