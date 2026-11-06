FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY shared/ /shared/
RUN pip install --default-timeout=100 --retries=5 /shared/

COPY services/processor/pyproject.toml .
RUN pip install --default-timeout=100 --retries=5 .

COPY services/processor/ .

# Run as an unprivileged user (no root inside the container).
RUN useradd --system --uid 10001 --no-create-home trustai
USER trustai

CMD ["python", "-c", "import asyncio; from app.consumer import start_consumer; asyncio.run(start_consumer())"]
