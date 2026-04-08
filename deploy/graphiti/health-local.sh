#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_ENV_FILE="$ROOT_DIR/deploy/graphiti/local.env"
REPO_ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$REPO_ENV_FILE" ]]; then
  set -a
  source "$REPO_ENV_FILE"
  set +a
fi

if [[ -f "$LOCAL_ENV_FILE" ]]; then
  set -a
  source "$LOCAL_ENV_FILE"
  set +a
fi

HOST="${GRAPHITI_SERVICE_HOST:-127.0.0.1}"
PORT="${GRAPHITI_SERVICE_PORT:-8182}"

exec curl "http://${HOST}:${PORT}/health"
