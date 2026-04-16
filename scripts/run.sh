#!/usr/bin/env bash
# Run a command inside the dev container.
#
# If already running inside the container (/.dockerenv exists), executes directly.
# Otherwise starts the container if needed and routes through docker compose exec.
#
# Usage:
#   ./scripts/run.sh pytest tests/unit/
#   ./scripts/run.sh ruff check src/
#   ./scripts/run.sh python -m mymodule
set -euo pipefail

COMPOSE_SERVICE="backend"

# Already inside the container — run directly
if [ -f /.dockerenv ]; then
    exec "$@"
fi

# Start the container if it is not already running
if ! docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^${COMPOSE_SERVICE}$"; then
    echo "[container] Starting dev container..." >&2
    docker compose up -d "${COMPOSE_SERVICE}" >&2
    # Brief pause for container to be ready
    sleep 1
fi

exec docker compose exec "${COMPOSE_SERVICE}" "$@"
