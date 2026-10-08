#!/bin/bash
BACKEND_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
PG_BIN="/usr/lib/postgresql/16/bin"
PGDATA="$BACKEND_DIR/pgdata"

echo "Stopping PostgreSQL server..."
$PG_BIN/pg_ctl -D "$PGDATA" stop -m fast || true
