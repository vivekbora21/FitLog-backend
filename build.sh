#!/usr/bin/env bash
# Render build script
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Run database seeding during build (idempotent, defaults to true)
if [ "${SEED_ON_BUILD:-true}" = "true" ]; then
    echo "==> Seeding database..."
    python manage.py seed_exercises
    python manage.py seed_fitlog_data
    python manage.py seed_vivek_journey
fi
