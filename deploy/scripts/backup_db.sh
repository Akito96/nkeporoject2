#!/usr/bin/env bash
set -euo pipefail

# Скрипт резервного копирования PostgreSQL (для ручного запуска или cron)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

source .env

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="${BACKUP_DIR}/coffee_shop_${TIMESTAMP}.sql.gz"

echo "Creating backup: ${FILENAME}"
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl \
    | gzip > "$FILENAME"

# Удаляем архивы старше RETENTION_DAYS дней
find "$BACKUP_DIR" -type f -name "coffee_shop_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

echo "Backup completed successfully."
