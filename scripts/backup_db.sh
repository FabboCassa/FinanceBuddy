#!/usr/bin/env bash
# Daily Postgres backup with rotation — run on the SERVER via cron.
#
# The DB volume holds the platform's real value (months of prices + scored
# news + forward impacts): losing it resets the Phase 4 self-calibration clock.
#
# Install (on the VM):
#   chmod +x scripts/backup_db.sh
#   crontab -e   →   30 5 * * * /home/ubuntu/FinanceBuddy/scripts/backup_db.sh >> /home/ubuntu/FinanceBuddy/backup/backup.log 2>&1
#
# Restore (DESTRUCTIVE — replaces current data):
#   gunzip -c backup/fb_YYYY-MM-DD.sql.gz | docker compose -f docker-compose.yml exec -T db psql -U "$DB_USER" -d "$DB_NAME"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${REPO_DIR}/backup"
KEEP_DAYS=14

cd "$REPO_DIR"
mkdir -p "$BACKUP_DIR"

# Read DB credentials from the production .env (never hardcode them here).
DB_NAME="$(grep -E '^DB_NAME=' .env | cut -d= -f2- || true)"
DB_USER="$(grep -E '^DB_USER=' .env | cut -d= -f2- || true)"
DB_NAME="${DB_NAME:-finance_buddy}"
DB_USER="${DB_USER:-postgres}"

STAMP="$(date +%F)"
OUT="${BACKUP_DIR}/fb_${STAMP}.sql.gz"

echo "[backup] $(date -Is) dumping ${DB_NAME} -> ${OUT}"
docker compose -f docker-compose.yml exec -T db \
  pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner | gzip > "$OUT"

# Sanity check: a healthy dump is never tiny.
SIZE=$(stat -c%s "$OUT")
if [ "$SIZE" -lt 10240 ]; then
  echo "[backup] ERROR: dump suspiciously small (${SIZE} bytes)" >&2
  exit 1
fi
echo "[backup] OK (${SIZE} bytes)"

# Rotate: drop dumps older than KEEP_DAYS.
find "$BACKUP_DIR" -name 'fb_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
