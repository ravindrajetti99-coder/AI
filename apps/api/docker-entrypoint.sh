#!/bin/sh
# Bring the schema up to date, optionally load the seed courses, then start the server.
set -e
alembic upgrade head
if [ "${SEED_ON_START:-false}" = "true" ]; then
    python -m app.seed
fi
exec "$@"
