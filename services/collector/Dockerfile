FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install system deps for cryptography + boto3
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*

COPY shared/ /shared/
RUN pip install --default-timeout=120 --retries=5 /shared/

COPY services/collector/pyproject.toml .
RUN pip install --default-timeout=120 --retries=5 .

COPY services/collector/ .

# Run as an unprivileged user (no root inside the container).
RUN useradd --system --uid 10001 --no-create-home trustai
USER trustai

CMD ["python", "-m", "app.main"]
