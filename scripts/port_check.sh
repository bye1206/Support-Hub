ss -tln | grep 5173
for h in 127.0.0.1 localhost; do (echo > /dev/tcp/$h/5173) 2>/dev/null && echo "$h OK" || echo "$h FAIL"; done
