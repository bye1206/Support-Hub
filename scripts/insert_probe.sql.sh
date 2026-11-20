set -a
. /mnt/e/Opencode/support-hub/.env
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "INSERT INTO outbox_events (id, event_type, aggregate_type, aggregate_id, idempotency_key, payload, status) VALUES (gen_random_uuid(), 'test.vite_probe', 'message', NULL, 'test-vite-probe-002', '{}', 'NEW');"
