#!/usr/bin/env bash
# scripts/install-watchdog.sh — install the watchdog cron entry.
# Run once per server. Idempotent.

set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the deploy user, not root." >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO/scripts/watchdog.sh"
LOG="/var/log/hermes-watchdog.log"

if [[ ! -x "$SCRIPT" ]]; then
  chmod +x "$SCRIPT"
fi

# Make sure the log file exists and is writable
sudo touch "$LOG"
sudo chown "$USER":"$USER" "$LOG"
sudo chmod 0644 "$LOG"

# Add crontab entry idempotently
CRON_LINE="*/5 * * * * $SCRIPT"
if crontab -l 2>/dev/null | grep -qF "$SCRIPT"; then
  echo "watchdog cron already installed"
else
  ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | crontab -
  echo "watchdog cron installed: $CRON_LINE"
fi

echo "Verify:"
echo "  crontab -l | grep watchdog"
echo "  tail -f $LOG"
