#!/usr/bin/env bash
# scripts/logs.sh <service> [lines] — tail logs for a service.
#
# Usage:
#   scripts/logs.sh crawler 100
#   scripts/logs.sh tailscale         # default 50 lines
#   scripts/logs.sh                   # follow all services live

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

svc="${1:-}"
n="${2:-50}"

if [[ -z "$svc" ]]; then
  docker compose logs -f --tail="$n"
else
  docker compose logs --tail="$n" -f "$svc"
fi
