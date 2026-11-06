# TrustAI Governance Service - multi-stage build, runs as a non-root user.
# Build from the repository root:  docker build -f services/governance/Dockerfile .

# ---- build stage: resolve and compile wheels ---------------------------------------------------
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=5
WORKDIR /build
COPY shared/ /build/shared/
COPY services/governance/pyproject.toml /build/governance/pyproject.toml
COPY services/governance/app /build/governance/app
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install /build/shared \
 && /opt/venv/bin/pip install "/build/governance"

# ---- runtime stage ----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 trustai \
 && useradd --system --uid 10001 --gid trustai --home-dir /app --shell /usr/sbin/nologin trustai
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=trustai:trustai services/governance/app /app/app
USER trustai
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
# API by default; the evaluation worker uses: python -m app.worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
