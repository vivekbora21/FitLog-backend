#!/bin/bash
PG_BIN="/usr/lib/postgresql/16/bin"
PGDATA="/home/vivek/Desktop/FitLog/backend/pgdata"
PORT=5433

if $PG_BIN/pg_isready -h localhost -p $PORT > /dev/null 2>&1; then
    echo "PostgreSQL is already running on port $PORT"
else
    echo "Starting PostgreSQL on port $PORT..."
    $PG_BIN/pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" -o "-p $PORT -k /tmp" start
fi
