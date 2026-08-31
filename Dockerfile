FROM python:3.12-slim AS base
WORKDIR /app
# Skip writing .pyc files: this app's runtime root filesystem is read-only
# in production (see osa-deploy's osa-backend Quadlets), and there's
# nothing to gain from bytecode-caching an image whose interpreter starts
# fresh on every deploy anyway. Also avoids a doomed write attempt every
# time docker-entrypoint.sh's `alembic upgrade head` freshly imports
# alembic/versions/*.py on container start.
ENV PYTHONDONTWRITEBYTECODE=1
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
# 1 worker: no cron/background-job coordination concern drives this
# choice anymore (cron jobs and ad-hoc background jobs both run
# exclusively in the dedicated osa-backend-worker container now, see
# app/worker/settings.py) -- raising this is a plain, independent
# capacity decision for the web process itself.
# --graceful-timeout matches --timeout above deliberately: a request can
# never legitimately run longer than --timeout (120s) without gunicorn
# already killing that worker as hung during normal operation, so a
# shutdown's grace period doesn't need to allow any more than that same
# ceiling (see osa-deploy's osa-backend Quadlet StopTimeout=/TimeoutStopSec=,
# which are sized off this same value plus a buffer).
CMD ["gunicorn", "main:app", "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", \
     "--graceful-timeout", "120", "--access-logfile", "-", "--no-control-socket"]
# --no-control-socket: this feature (gunicorn >= 25.1.0) is for gunicornc,
# a CLI tool for runtime worker management -- unused here (Podman/systemd
# own the container lifecycle instead). Without this flag, gunicorn tries
# to create $HOME/.gunicorn/gunicorn.ctl by default, which fails with a
# permission error on every start: the app user above is created with
# --no-create-home, so its $HOME (/home/app) was never actually created.
