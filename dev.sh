#!/bin/bash
# Development startup script

# Load environment variables
set -a
source .env
set +a

# Override database path for local development
export DATABASE_PATH="$(pwd)/data/music.duckdb"

echo "Starting music service on port 8100..."
cd service
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload &
SERVICE_PID=$!
cd ..

sleep 2

echo "Starting frontend on port 3100..."
cd frontend
NUXT_MUSIC_SERVICE_URL=http://127.0.0.1:8100 pnpm dev --port 3100 &
FRONTEND_PID=$!
cd ..

echo ""
echo "Services started:"
echo "  Frontend: http://localhost:3100"
echo "  Service:  http://localhost:8100"
echo ""
echo "Press Ctrl+C to stop all services"

trap "kill $SERVICE_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
