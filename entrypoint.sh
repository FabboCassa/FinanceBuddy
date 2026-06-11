#!/usr/bin/env bash
# Container entrypoint shared by web / worker / beat services.
# Waits for Postgres, then (gated by env) applies migrations and bootstraps
# Phase 1 seed data before exec-ing the service command (CMD / compose command).
set -e

# --- Wait for the database -------------------------------------------------
if [ -n "$DB_HOST" ]; then
  echo "[entrypoint] Waiting for database at ${DB_HOST}:${DB_PORT:-5432}..."
  until python - <<'PY'
import os, sys
import psycopg2
try:
    psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
    ).close()
except Exception as exc:
    print(f"[entrypoint] DB not ready: {exc}", file=sys.stderr)
    sys.exit(1)
PY
  do
    sleep 2
  done
  echo "[entrypoint] Database is up."
fi

# --- Apply migrations (web service only, to avoid concurrent runners) -------
if [ "${RUN_MIGRATIONS:-False}" = "True" ]; then
  echo "[entrypoint] Applying migrations..."
  python manage.py migrate --noinput
fi

# --- Collect static files (admin assets for WhiteNoise; web service only) ---
if [ "${RUN_COLLECTSTATIC:-False}" = "True" ]; then
  echo "[entrypoint] Collecting static files..."
  python manage.py collectstatic --noinput
fi

# --- Phase 1 bootstrap: seed assets + backfill history ----------------------
if [ "${RUN_BOOTSTRAP:-False}" = "True" ]; then
  echo "[entrypoint] Bootstrapping seed data..."
  # Sentiment is left to the Celery worker to keep the web image light.
  python manage.py bootstrap_assets --no-sentiment || \
    echo "[entrypoint] Bootstrap reported errors (continuing)."
fi

exec "$@"
