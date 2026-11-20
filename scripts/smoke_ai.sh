BASE=http://10.9.79.252:8000
KEY="osp-prod_mYrgUrlBBF5h501a3oS8Y6bYAPF-pNEl8HPbTwGGhqM"
ID=61375
echo "--- operator trigger check (может занять до 2 мин):"
curl -s --max-time 130 -X POST $BASE/api/v1/message/$ID -H "X-API-Key: $KEY" -H "X-User-Id: supporthub-test-001" -H "X-Source: support-hub" -H "Content-Type: application/json" -d "{\"query\":\"оператор\"}" | head -c 300
echo
