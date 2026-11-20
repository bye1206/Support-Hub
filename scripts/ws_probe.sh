set -a
. /mnt/e/Opencode/support-hub/.env
(timeout 45 redis-cli --raw subscribe support_hub:events > /tmp/ws_probe.log 2>&1 &)
sleep 2
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "INSERT INTO outbox_events (id, event_type, aggregate_type, aggregate_id, idempotency_key, payload, status) VALUES (gen_random_uuid(), 'test.ws_probe', 'message', NULL, 'test-ws-probe-001', '{}', 'NEW');"
echo "inserted, waiting for outbox cron..."
sleep 25
pkill -f "redis-cli --raw subscribe" 2>/dev/null
echo "--- captured:"
head -20 /tmp/ws_probe.log
