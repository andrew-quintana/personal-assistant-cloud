#!/usr/bin/env bash
# scripts/watchdog.sh — host-level watchdog. Run from cron every 5 minutes.
#
# Belt-and-suspenders behind autoheal: pings the agent's /health and
# restarts the crawler if it doesn't respond. Logs every tick.

set -u

LOG="/var/log/hermes-watchdog.log"
COMPOSE_DIR="/home/deploy/hermes"

log() { printf "%s %s\n" "$(date '+%F %T')" "$*" >> "$LOG"; }

# Rotate log if it gets large (>5 MB)
if [[ -f "$LOG" ]] && [[ $(stat -c %s "$LOG" 2>/dev/null || echo 0) -gt 5242880 ]]; then
  mv "$LOG" "$LOG.1"
  : > "$LOG"
fi

log "tick"

if curl -fsS -m 10 http://localhost:8000/health >/dev/null 2>&1; then
  exit 0
fi

log "crawler /health failed — restarting"
cd "$COMPOSE_DIR" || { log "ERROR: $COMPOSE_DIR not found"; exit 1; }
if docker compose restart crawler >>"$LOG" 2>&1; then
  log "crawler restart issued"
else
  log "ERROR: docker compose restart crawler failed"
fi
