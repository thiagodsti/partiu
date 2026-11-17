#!/bin/bash
# run_e2e.sh — run the Playwright suite against a throwaway server.
#
#   scripts/run_e2e.sh                 # whole suite
#   scripts/run_e2e.sh tests/foo.spec.ts --workers=1   # any playwright args
#
# Starts its own server on a scratch database and stops it afterwards. Global
# setup creates test accounts and seeded trips in whatever server it reaches,
# so this refuses to run when port 8000 is already taken — otherwise the suite
# would quietly write into that instance's database instead. The frontend must
# already be built (`npm run build`); CI builds it in an earlier step.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8000
URL="http://127.0.0.1:${PORT}"

if curl -s -o /dev/null --max-time 2 "${URL}/"; then
  echo "run_e2e: something is already listening on port ${PORT}; stop it first." >&2
  echo "run_e2e: the suite would otherwise create test accounts in that server's database." >&2
  exit 1
fi

SCRATCH="$(mktemp -d)"
LOG="${E2E_SERVER_LOG:-${SCRATCH}/server.log}"
SERVER_PID=""

cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -rf "${SCRATCH}"
}
trap cleanup EXIT

cd "${ROOT}"
# DISABLE_RATE_LIMITS: two dozen sign-ins from one address in a minute.
# SECURE_COOKIES=false: the suite talks plain http to localhost.
DB_PATH="${SCRATCH}/partiu.db" DISABLE_SCHEDULER=true DISABLE_RATE_LIMITS=true SECURE_COOKIES=false \
  uv run uvicorn backend.main:app --host 127.0.0.1 --port "${PORT}" > "${LOG}" 2>&1 &
SERVER_PID=$!

# The first boot loads the airports table, which the seeded trips need.
for _ in $(seq 1 90); do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "run_e2e: the server exited during startup:" >&2
    cat "${LOG}" >&2
    exit 1
  fi
  curl -s -o /dev/null --max-time 2 "${URL}/api/version" && break
  sleep 1
done
if ! curl -s -o /dev/null --max-time 2 "${URL}/api/version"; then
  echo "run_e2e: the server did not answer within 90s:" >&2
  cat "${LOG}" >&2
  exit 1
fi

cd "${ROOT}/frontend"
npx playwright test "$@"
