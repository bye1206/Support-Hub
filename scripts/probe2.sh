set -a
. /mnt/e/Opencode/support-hub/.env
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "UPDATE outbox_events SET status='NEW', attempts=0, processed_at=NULL, next_attempt_at=NULL, lease_expires_at=NULL WHERE idempotency_key='test-vite-probe-002';"
