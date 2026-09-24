#!/bin/bash
set -e

PG_BIN="/usr/lib/postgresql/16/bin"
PGDATA="/home/vivek/Desktop/FitLog/backend/pgdata"
PORT=5433
DB_NAME="fitlog_db"
DB_USER="fitlog_user"

if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL cluster in $PGDATA..."
    $PG_BIN/initdb -D "$PGDATA" -U "$DB_USER" --auth=trust
    echo "Cluster initialized successfully."
fi

# Check if postgres is already running
if ! $PG_BIN/pg_isready -h localhost -p $PORT > /dev/null 2>&1; then
    echo "Starting PostgreSQL server on port $PORT..."
    $PG_BIN/pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" -o "-p $PORT -k /tmp" start
    sleep 1
fi

# Ensure database exists
if ! $PG_BIN/psql -h localhost -p $PORT -U "$DB_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    echo "Creating database $DB_NAME..."
    $PG_BIN/createdb -h localhost -p $PORT -U "$DB_USER" "$DB_NAME"
    echo "Database $DB_NAME created."
else
    echo "Database $DB_NAME already exists."
fi

echo "PostgreSQL is ready on localhost:$PORT (database: $DB_NAME, user: $DB_USER)"

# Run Django migrations and seed exercises
BACKEND_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
if [ -f "$BACKEND_DIR/manage.py" ]; then
    echo "Running Django migrations..."
    python "$BACKEND_DIR/manage.py" migrate --run-syncdb 2>/dev/null || true
    echo "Seeding exercise catalog..."
    python "$BACKEND_DIR/manage.py" seed_exercises 2>/dev/null || true
fi
