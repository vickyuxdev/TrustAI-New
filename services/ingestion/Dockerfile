# Multi-stage Dockerfile for all FastAPI services
# Build context: TrustAI root (so shared/ is available)
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install shared library
COPY shared/ /shared/
RUN pip install --default-timeout=100 --retries=5 /shared/

# Install service dependencies
COPY services/ingestion/pyproject.toml .
RUN pip install --default-timeout=100 --retries=5 .

COPY services/ingestion/ .

# Run as an unprivileged user (no root inside the container).
RUN useradd --system --uid 10001 --no-create-home trustai
USER trustai

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
