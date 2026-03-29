#!/bin/bash
set -e

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')

# Load .env so we can read OLLAMA_URL
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -v '^$' | xargs) 2>/dev/null || true
fi

# Start Ollama if OLLAMA_URL points to localhost and ollama is installed
OLLAMA_PID=""
if [ -n "$OLLAMA_URL" ] && echo "$OLLAMA_URL" | grep -qE 'localhost|127\.0\.0\.1'; then
  if command -v ollama &>/dev/null; then
    if ! curl -s --max-time 1 "${OLLAMA_URL}/api/tags" &>/dev/null; then
      echo "  Starting Ollama..."
      ollama serve &>/dev/null &
      OLLAMA_PID=$!
      # Wait up to 10s for Ollama to be ready
      for i in $(seq 1 10); do
        curl -s --max-time 1 "${OLLAMA_URL}/api/tags" &>/dev/null && break
        sleep 1
      done
      if curl -s --max-time 1 "${OLLAMA_URL}/api/tags" &>/dev/null; then
        echo "  Ollama ready  (model: ${OLLAMA_MODEL:-qwen2.5:1.5b})"
      else
        echo "  Ollama failed to start — LLM fallback disabled."
      fi
      # Pull the model if not already present
      ollama pull "${OLLAMA_MODEL:-qwen2.5:1.5b}" 2>/dev/null || true
    else
      echo "  Ollama already running  (model: ${OLLAMA_MODEL:-qwen2.5:1.5b})"
    fi
  else
    echo "  Warning: OLLAMA_URL is set but 'ollama' is not installed. LLM fallback disabled."
  fi
fi

# Kill any leftover processes and wait for ports to be free
pkill -f "uvicorn backend.main" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
kill $(lsof -ti :8000 :5173 :5174 :5175 :2525 2>/dev/null) 2>/dev/null || true
# Wait until port 8000 is actually free (up to 8 seconds)
for i in $(seq 1 8); do
  lsof -ti :8000 &>/dev/null || break
  sleep 1
done

# Start backend
uv run uvicorn backend.main:app --reload --host 0.0.0.0 &
BACKEND_PID=$!

# Start frontend (subshell keeps the cd local so we don't change the script's cwd)
(cd frontend && npm run dev -- --host) &
FRONTEND_PID=$!

echo ""
echo "  Local:   http://localhost:5173"
if [ -n "$LOCAL_IP" ]; then
  echo "  Network: http://$LOCAL_IP:5173  (open this on your phone)"
fi
echo ""
echo "Press Ctrl+C to stop both."

cleanup() {
  # Kill process groups to ensure Vite child processes are also terminated
  kill -- -$BACKEND_PID -$FRONTEND_PID ${OLLAMA_PID:+-$OLLAMA_PID} 2>/dev/null || true
  kill $BACKEND_PID $FRONTEND_PID ${OLLAMA_PID} 2>/dev/null || true
  pkill -f "uvicorn backend.main" 2>/dev/null || true
  pkill -f "vite" 2>/dev/null || true
  kill $(lsof -ti :8000 :5173 :5174 :5175 :2525 2>/dev/null) 2>/dev/null || true
  exit
}
trap cleanup INT TERM
wait
