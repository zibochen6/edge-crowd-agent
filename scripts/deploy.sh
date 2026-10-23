#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE="${CROWD_SSH:?Set CROWD_SSH to user@JETSON_IP}"
DEST="${CROWD_REMOTE_DIR:-/home/seeed/mtp_demo/edge-crowd-agent}"
if [[ ! "$DEST" =~ ^/[a-zA-Z0-9_./-]+$ ]]; then echo 'CROWD_REMOTE_DIR must be an absolute path without spaces or shell characters.' >&2; exit 1; fi
if ! test -d frontend/node_modules; then (cd frontend && npm ci); fi
(cd frontend && npm run build)
ssh "$REMOTE" "mkdir -p '$DEST'"
rsync -az --exclude '.git/' --include '.env.example' --exclude '.env*' --exclude '.venv*' --exclude node_modules --exclude data --exclude __pycache__ --exclude .pytest_cache ./ "$REMOTE:$DEST/"
ssh "$REMOTE" "cd '$DEST' && bash start.sh stop && bash scripts/setup.sh && bash start.sh"
