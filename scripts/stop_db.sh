#!/bin/bash
PG_BIN="/usr/lib/postgresql/16/bin"
PGDATA="/home/vivek/Desktop/FitLog/backend/pgdata"

echo "Stopping PostgreSQL server..."
$PG_BIN/pg_ctl -D "$PGDATA" stop -m fast || true
