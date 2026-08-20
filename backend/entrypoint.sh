#!/bin/sh
# Applies outstanding Alembic migrations before the app starts, so a fresh
# compose volume (schema only at the init_scripts baseline) or one left
# behind at an older revision is never served against a stale schema.
# Gated by RUN_MIGRATIONS so only one process runs it — set on the backend
# service, left unset on celery-worker, which shares this image/entrypoint.
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "entrypoint: running alembic upgrade head..."
    alembic upgrade head
fi

exec "$@"
