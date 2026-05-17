#!/usr/bin/env bash
# scripts/repair.sh — diagnostic + auto-fix for common failure modes.
#
# Runs through known issues, prints what it sees, and attempts fixes.
# Idempotent — safe to re-run.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
warn() { printf "  ⚠ %s\n" "$*"; }
bad()  { printf "  ✗ %s\n" "$*"; }
fix()  { printf "  → %s\n" "$*"; }

bold "1. Docker daemon"
if docker info >/dev/null 2>&1; then
  ok "daemon responding"
else
  bad "daemon unreachable — run: sudo systemctl restart docker"
  exit 1
fi

bold "2. Compose stack"
if ! docker compose ps >/dev/null 2>&1; then
  bad "compose can't read compose file; check you're in repo root"
  exit 1
fi
ok "compose file readable"

bold "3. .env presence"
if [[ -f .env ]]; then
  ok ".env exists"
else
  bad "missing .env — copy from .env.example and fill in"
  exit 1
fi

bold "4. Tailscale auth state"
if docker exec hermes-tailscale tailscale status >/dev/null 2>&1; then
  ok "tailscale authenticated"
else
  warn "tailscale not authenticated"
  fix "check logs: docker logs hermes-tailscale"
  fix "if TS_AUTHKEY in .env is expired, generate a new one + recreate:"
  fix "    docker compose up -d --force-recreate tailscale"
fi

bold "5. Tailscale cert files"
if docker run --rm -v hermes_ts-certs:/c alpine ls /c 2>/dev/null | grep -q .crt; then
  ok "cert files present"
else
  warn "no cert files in ts-certs volume"
  fix "tailscale container hasn't completed cert issuance"
  fix "    docker logs hermes-tailscale | grep cert"
fi

bold "6. Caddy"
caddy_status=$(docker inspect -f '{{.State.Status}}' hermes-caddy 2>/dev/null || echo missing)
if [[ "$caddy_status" == "running" ]]; then
  ok "caddy running"
else
  warn "caddy status: $caddy_status"
  fix "    docker compose restart caddy"
fi

bold "7. Crawler / agent"
if curl -fsS -m 5 http://localhost:8000/health >/dev/null 2>&1; then
  ok "agent /health responding"
else
  bad "agent /health failing"
  fix "    docker compose logs --tail=50 crawler"
  fix "    docker compose restart crawler"
fi

bold "8. Conduit (Matrix)"
conduit_status=$(docker inspect -f '{{.State.Status}}' hermes-conduit 2>/dev/null || echo missing)
if [[ "$conduit_status" == "running" ]]; then
  ok "conduit running"
else
  bad "conduit status: $conduit_status"
  fix "    docker compose logs --tail=50 conduit"
  fix "    docker compose restart conduit"
fi

bold "9. Disk pressure"
used_pct=$(df / | tail -1 | awk '{print $5}' | tr -d %)
if [[ "$used_pct" -lt 80 ]]; then
  ok "/ at ${used_pct}% full"
elif [[ "$used_pct" -lt 90 ]]; then
  warn "/ at ${used_pct}% full — getting tight"
  fix "    docker system prune -a --volumes  # frees a lot, careful"
else
  bad "/ at ${used_pct}% full — urgent"
fi

bold "Done."
