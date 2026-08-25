FROM python:3.12-slim AS base
WORKDIR /app
# postgresql-client-18: pg_dump/pg_restore/psql, used by
# app/services/backup_service.py and scripts/backup_db.py/restore_db.py.
# Shared by dev and prod (both need to run backups/restores). Pinned via
# the official PGDG repo instead of Debian's bundled version (Debian
# trixie only ships v17) -- pg_dump/pg_restore/psql must be >= the
# Postgres server's major version to safely dump from and restore into it
# across a major-version upgrade.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg postgresql-common \
    && sh /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y --auto-remove curl gnupg \
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
# Installs from the lock file, not requirements-dev.txt directly -- the
# same pinned versions CI installs via `uv pip install --system -r
# requirements-dev.lock`, so a routine image rebuild can never silently
# pick up a newer ruff/pyright/pytest from PyPI than what pre-commit and
# CI are actually gated on. requirements-dev.lock already transitively
# includes requirements.txt's runtime pins, so no separate
# requirements.txt copy is needed here.
COPY requirements-dev.lock ./
RUN pip install --no-cache-dir -r requirements-dev.lock
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
# 1 worker: the scheduler's pg_try_advisory_lock guard (see
# app/core/scheduler.py) makes >1 worker safe against double-firing cron
# jobs, but raising the worker count itself is an intentionally separate
# follow-up decision, not part of the structural 1:1 DB transfer.
CMD ["gunicorn", "main:app", "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--access-logfile", "-"]
