FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY alembic.ini ./alembic.ini
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --create-home bidtrace \
    && mkdir -p /app/data/uploads \
    && chown -R bidtrace:bidtrace /app/data

USER bidtrace

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
