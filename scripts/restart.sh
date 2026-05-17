#!/usr/bin/env bash
# scripts/restart.sh [service] — restart one service or the whole stack.
#
# Usage:
#   scripts/restart.sh             # restarts everything
#   scripts/restart.sh crawler     # restarts just the crawler
#   scripts/restart.sh -all-       # explicit "everything"

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

svc="${1:--all-}"

if [[ "$svc" == "-all-" || -z "$svc" ]]; then
  echo "Restarting entire stack..."
  docker compose restart
else
  echo "Restarting $svc..."
  docker compose restart "$svc"
fi

echo ""
"$(dirname "${BASH_SOURCE[0]}")/health.sh"
