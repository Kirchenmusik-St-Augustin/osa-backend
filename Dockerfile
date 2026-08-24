FROM python:3.12-slim AS base
WORKDIR /app
# postgresql-client: pg_dump/pg_restore/psql, used by
# app/services/backup_service.py and scripts/backup_db.py/restore_db.py.
# Shared by dev and prod (both need to run backups/restores).
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.lock .
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

FROM base AS dev
# libatomic1: required by pyright's bundled prebuilt Node.js runtime, which
# is missing from the python:3.12-slim base image.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --no-create-home app
COPY --from=builder /install /usr/local
COPY --chown=app:app . .
RUN chmod +x docker-entrypoint.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"]
ENTRYPOINT ["./docker-entrypoint.sh"]
# 1 worker: matched Phase 1 (SQLite, where the scheduler's
# pg_try_advisory_lock guard -- see app/core/scheduler.py -- is a no-op, so
# >1 worker would double-fire every cron job). Postgres (Phase 2) makes
# that guard meaningful, but the worker count itself is an intentionally
# separate follow-up decision, not part of the 1:1 structural DB transfer.
CMD ["gunicorn", "main:app", "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--access-logfile", "-"]
