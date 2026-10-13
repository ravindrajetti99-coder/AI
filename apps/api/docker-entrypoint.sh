#!/bin/sh
# Bring the schema up to date, optionally load the seed courses, then run the command
# (the API server by default, or `python -m app.worker`). Set MIGRATE_ON_START=false where
# another service or a release step runs the migrations.
set -e
if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
    alembic upgrade head
fi
if [ "${SEED_ON_START:-false}" = "true" ]; then
    python -m app.seed
fi
exec "$@"
