#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if test -f .env; then set -a; source .env; set +a; fi
if ! test -x .venv/bin/python; then bash scripts/setup.sh; fi
if test "${1:-start}" = start && ! test -f frontend/dist/index.html; then
    (cd frontend && npm ci && npm run build)
fi
exec .venv/bin/python scripts/service.py "${1:-start}"
