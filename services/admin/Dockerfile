FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY shared/ /shared/
RUN pip install --default-timeout=100 --retries=5 /shared/

COPY services/admin/pyproject.toml .
RUN pip install --default-timeout=100 --retries=5 .

COPY services/admin/ .

# Run as an unprivileged user (no root inside the container).
RUN useradd --system --uid 10001 --no-create-home trustai
USER trustai

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
