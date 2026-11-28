#!/bin/bash
# run_e2e.sh — run the Playwright suite against a throwaway server.
#
#   scripts/run_e2e.sh                                  # whole suite
#   scripts/run_e2e.sh tests/foo.spec.ts --workers=1    # any playwright args
#
# Starts its own server on a scratch database and stops it afterwards. Global
# setup creates test accounts and seeded trips in whatever server it reaches,
# so the suite must only ever reach this one: the port is bound *before* the
# server starts and handed to uvicorn (--fd), so a busy port is refused up
# front and nothing else can take it while the app boots. The frontend must
# already be built (`npm ci && npm run build` in frontend/); CI does that first.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8000
URL="http://127.0.0.1:${PORT}"
# What the suite is told: "localhost", because older specs hard-code
# http://localhost:8000 and a session cookie set for 127.0.0.1 is not sent there.
SUITE_URL="http://localhost:${PORT}"

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
# A per-run key unless one is given: the scratch database holds nothing worth
# encrypting, and the backend refuses to start without one.
export SECRET_KEY="${SECRET_KEY:-e2e-$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')}"
# DISABLE_RATE_LIMITS: two dozen sign-ins from one address in a minute.
# SECURE_COOKIES=false: the suite talks plain http to localhost.
# DEMO_MODE=false: a demo refuses the account creation global setup does, and a
# root .env written for a demo instance would otherwise switch it on here.
export DB_PATH="${SCRATCH}/partiu.db" DISABLE_SCHEDULER=true DISABLE_RATE_LIMITS=true SECURE_COOKIES=false DEMO_MODE=false
# No geocoder and no AI, whatever the root .env says: komoot's public Photon
# blocks an address that hammers it and an AI provider bills per request. Set
# to empty rather than unset, because load_dotenv never overrides a variable
# that exists. Specs that show those features answer the endpoints in the
# browser (page.route); checking them against a real Photon or model is a
# manual test, against a local one only (AGENTS.md, "Manual tests").
export PHOTON_URL="" OLLAMA_URL="" OLLAMA_MODEL=""
export AI_SUGGESTIONS_PROVIDER="" AI_SUGGESTIONS_API_KEY="" AI_SUGGESTIONS_BASE_URL="" AI_SUGGESTIONS_MODEL=""
# KDE Itinerary's extractor is x86_64-only and ships in the Docker image, so the
# suite runs against a stand-in that answers for one marked email only (see the
# script, and tests/kitinerary-import.spec.ts).
export KITINERARY_EXTRACTOR="${KITINERARY_EXTRACTOR:-${ROOT}/frontend/tests/fixtures/fake-kitinerary-extractor}"

# Bind first, then exec uvicorn on the inherited socket. Binding fails at once
# if anything holds the port — no check-then-start window for another instance.
uv run python - "${PORT}" > "${LOG}" 2>&1 <<'PY' &
import os, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# Linux only: lets a rerun bind while the last run's connections sit in
# TIME_WAIT, and still refuses a second live listener. On BSD/macOS the same
# option would let this bind 127.0.0.1 beside a server already on 0.0.0.0 —
# exactly what binding first exists to prevent — so it keeps the strict bind,
# and an immediate rerun there may have to wait out TIME_WAIT.
if sys.platform.startswith("linux"):
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError as e:
    sys.exit(f"run_e2e: port {sys.argv[1]} is in use ({e}); stop whatever holds it first.")
s.listen(128)
os.set_inheritable(s.fileno(), True)
os.execvp("uv", ["uv", "run", "uvicorn", "backend.main:app", "--fd", str(s.fileno())])
PY
SERVER_PID=$!

# The first boot loads the airports table, which the seeded trips need.
# public-config answers 200 even before first-run setup; /api/version does not.
# --noproxy: a shell http_proxy must not intercept a loopback probe.
ready() { curl -sf --noproxy '*' -o /dev/null --max-time 2 "${URL}/api/auth/public-config"; }
for _ in $(seq 1 90); do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "run_e2e: the server exited during startup:" >&2
    cat "${LOG}" >&2
    exit 1
  fi
  ready && break
  sleep 1
done
if ! ready; then
  echo "run_e2e: the server did not answer within 90s:" >&2
  cat "${LOG}" >&2
  exit 1
fi

cd "${ROOT}/frontend"
# E2E_BASE_URL pinned to this server, whatever the shell had; E2E_MANAGED tells
# global setup that a failed admin sign-in here is a broken run, not someone
# else's server.
E2E_BASE_URL="${SUITE_URL}" E2E_MANAGED=1 npx playwright test "$@"
