set -a
. /mnt/e/Opencode/support-hub/.env
PGPASSWORD="$POSTGRES_PASSWORD" timeout 30 psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /mnt/e/Opencode/support-hub/scripts/dbq.sql 2>&1
