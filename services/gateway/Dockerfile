# TrustAI AI Gateway - multi-stage build, runs as a non-root user.
# Build from the repository root:  docker build -f services/gateway/Dockerfile .

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=100 PIP_RETRIES=5
WORKDIR /build
COPY services/gateway/pyproject.toml /build/gateway/pyproject.toml
COPY services/gateway/app /build/gateway/app
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install /build/gateway

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 trustai \
 && useradd --system --uid 10001 --gid trustai --home-dir /app --shell /usr/sbin/nologin trustai
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=trustai:trustai services/gateway/app /app/app
COPY --chown=trustai:trustai services/gateway/upstreams.example.yaml /app/upstreams.yaml
USER trustai
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
