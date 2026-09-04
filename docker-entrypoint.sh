#!/bin/bash
set -e

# No htpasswd generation. The nginx basic auth this used to feed is gone (see
# nginx/app.conf); authentication belongs to the reverse proxy in front of this
# container. The `else` branch here used to write admin/admin whenever AUTH_USER
# or AUTH_PASS was unset, which is a default credential nobody asked for.

# Start uvicorn in background
echo "Starting uvicorn..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

# Wait for uvicorn to be ready
echo "Waiting for backend to be ready..."
for i in {1..60}; do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "Backend is ready"
        break
    fi
    sleep 1
done

# Trap SIGTERM for graceful shutdown
cleanup() {
    echo "Shutting down..."
    kill $UVICORN_PID 2>/dev/null || true
    wait $UVICORN_PID 2>/dev/null || true
    nginx -s quit 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Run nginx in foreground
echo "Starting nginx..."
nginx -g 'daemon off;' &
NGINX_PID=$!

# Wait for either process to exit
wait -n $UVICORN_PID $NGINX_PID

# If we get here, one of the processes died
echo "A process exited unexpectedly"
cleanup
