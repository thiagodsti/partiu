#!/bin/bash
set -e

# Start backend
uv run uvicorn backend.main:app --reload &
BACKEND_PID=$!

# Start frontend
cd frontend && npm run dev &
FRONTEND_PID=$!

echo "Backend running (PID $BACKEND_PID) at http://localhost:8000"
echo "Frontend running (PID $FRONTEND_PID) at http://localhost:5173"
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
