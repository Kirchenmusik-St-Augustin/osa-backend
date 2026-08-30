#!/bin/sh
# Applies pending Alembic migrations before the app starts, so a container
# restart (e.g. triggered by podman-auto-update pulling a new image) can
# never run new code against an unmigrated schema. Skipped when
# SKIP_MIGRATIONS=true -- set by the dedicated arq worker container, which
# shares this exact image/entrypoint with the web container and must not
# also independently run migrations on every restart cycle.
set -e

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

exec "$@"
