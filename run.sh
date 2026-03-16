#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p data

# Build frontend (Svelte + Vite)
echo "Building frontend..."
cd frontend
npm install --silent 2>&1 | grep -v ExperimentalWarning | grep -v "loading ES Module" | grep -v "trace-warnings" || true
npm run build 2>&1 | grep -v ExperimentalWarning | grep -v "loading ES Module" | grep -v "trace-warnings"
cd ..

# Activate venv
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo "Starting server..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
