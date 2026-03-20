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

# Set up venv if missing or pointing to a dead Python interpreter
if ! venv/bin/python -c "import sys" 2>/dev/null; then
    echo "Setting up Python virtual environment..."
    rm -rf venv
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
elif ! venv/bin/python -c "import uvicorn" 2>/dev/null; then
    echo "Installing dependencies..."
    venv/bin/pip install -r requirements.txt
fi

echo "Starting server..."
venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
