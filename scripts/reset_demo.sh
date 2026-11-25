#!/bin/sh
# reset_demo.sh — wipe the demo's data and reseed it with trips dated relative
# to today. The work is done by scripts/reset_demo.py inside the app container
# (see its docstring); this only finds the compose project and calls it.
#
# Run from the demo's compose directory, or pass it as the first argument:
#   sh scripts/reset_demo.sh /path/to/partiu-demo
# Scheduled on the host every 6 hours (00:00, 06:00, 12:00, 18:00 UTC), the
# times the demo banner advertises.

set -e

cd "${1:-$(dirname "$0")/..}"
exec docker compose exec -T app python /app/scripts/reset_demo.py
