#!/bin/bash
set -e

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')

# Start backend
uv run uvicorn backend.main:app --reload --host 0.0.0.0 &
BACKEND_PID=$!

# Start frontend
cd frontend && npm run dev -- --host &
FRONTEND_PID=$!

echo ""
echo "  Local:   http://localhost:5173"
if [ -n "$LOCAL_IP" ]; then
  echo "  Network: http://$LOCAL_IP:5173  (open this on your phone)"
fi
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
