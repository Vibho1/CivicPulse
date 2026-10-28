#!/bin/sh
# Container entrypoint (see Dockerfile).
#
# Without LITESTREAM_REPLICA_URL this just starts the API. With it (Cloud Run), the SQLite DB
# lives on the container's local disk and Litestream:
#   1. restores the latest copy from Cloud Storage on a cold start (no-op on the very first boot);
#   2. streams every change back to Cloud Storage while the API runs, with a final sync when
#      Cloud Run stops the instance.
# Run exactly one instance (Cloud Run --max-instances=1): SQLite has a single writer.
set -eu

# Only Cloud Run's front end can reach the container, so trust its X-Forwarded-* headers: links the
# API builds (escalation drafts, WhatsApp replies) then use the public https URL. (Set via the
# environment: a literal * in $APP would be glob-expanded below.)
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
APP="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"

if [ -z "${LITESTREAM_REPLICA_URL:-}" ]; then
  exec $APP
fi

# Must match the API's DATABASE_PATH default (backend/app/config.py).
DB="${DATABASE_PATH:-/app/backend/data/civicpulse.db}"
mkdir -p "$(dirname "$DB")"
echo "litestream: restoring $DB from $LITESTREAM_REPLICA_URL (if a replica exists)"
litestream restore -if-db-not-exists -if-replica-exists -o "$DB" "$LITESTREAM_REPLICA_URL"
# First boot: create the file in WAL mode (which Litestream needs) before replication starts.
python -c 'import sqlite3, sys; sqlite3.connect(sys.argv[1]).execute("PRAGMA journal_mode=WAL").fetchall()' "$DB"
exec litestream replicate -exec "$APP" "$DB" "$LITESTREAM_REPLICA_URL"
