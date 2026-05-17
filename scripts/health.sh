#!/usr/bin/env bash
# scripts/health.sh — quick stack status check.
# Usage: scripts/health.sh
#
# Prints each container, its docker status, its healthcheck state, and a
# probe against the agent's HTTP /health.

set -u

cd "$(dirname "${BASH_SOURCE[0]}")/.."

printf "%-22s %-30s %s\n" "CONTAINER" "STATUS" "HEALTH"
printf "%-22s %-30s %s\n" "---------" "------" "------"

for c in $(docker compose ps -a --format '{{.Name}}' 2>/dev/null); do
  status=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo unknown)
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}—{{end}}' "$c" 2>/dev/null || echo unknown)
  printf "%-22s %-30s %s\n" "$c" "$status" "$health"
done

echo ""
echo "--- agent /health ---"
if curl -fsS -m 5 http://localhost:8000/health 2>/dev/null; then
  echo ""
else
  echo "  (unreachable)"
fi

echo ""
echo "--- tailscale ---"
docker exec hermes-tailscale tailscale status 2>&1 | head -5 || echo "  (tailscale container not running)"
