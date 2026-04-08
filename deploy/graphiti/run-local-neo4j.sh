#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_ENV_FILE="$ROOT_DIR/deploy/graphiti/local.env"
REPO_ENV_FILE="$ROOT_DIR/.env"
COMMAND="${1:-up}"

mkdir -p \
  "$ROOT_DIR/deploy/graphiti/neo4j/data" \
  "$ROOT_DIR/deploy/graphiti/neo4j/logs" \
  "$ROOT_DIR/deploy/graphiti/neo4j/plugins"

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

export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-personagraph-local}"

cd "$ROOT_DIR/deploy/graphiti"

case "$COMMAND" in
  up)
    exec docker compose up -d
    ;;
  down)
    exec docker compose down
    ;;
  logs)
    exec docker compose logs -f neo4j
    ;;
  *)
    echo "Usage: $0 [up|down|logs]" >&2
    exit 1
    ;;
esac
