#!/usr/bin/env bash
# scripts/sync-cookies.sh — Mac-side helper.
#
# 1. Opens a headed Chromium via Playwright so you can log in to a site.
# 2. Saves the Playwright storage_state to data/cookies/<site>_cookies.json.
# 3. SCPs the result to the cloud server's /data/cookies dir over Tailscale.
#
# Usage:
#   scripts/sync-cookies.sh facebook
#   scripts/sync-cookies.sh gmail
#
# Prereqs on your Mac:
#   pip3 install playwright && playwright install chromium
#
# Server target is read from $HERMES_SSH_HOST or defaults to the
# Tailscale-aware deploy address you used during setup.

set -euo pipefail

site="${1:-}"
if [[ -z "$site" ]]; then
  echo "Usage: $0 <facebook|gmail|...>" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Step 1: open a headed browser locally, capture session
python3 scripts/save-cookies.py "$site"

# Locate the produced file
case "$site" in
  facebook) file="data/cookies/fb_cookies.json" ;;
  gmail)    file="data/cookies/gmail_cookies.json" ;;
  *) echo "Unknown site: $site (update site→filename mapping in sync-cookies.sh)" >&2; exit 1 ;;
esac

if [[ ! -f "$file" ]]; then
  echo "Expected $file but it's not there. Did the login step succeed?" >&2
  exit 1
fi

# Step 2: scp to server. Default to Tailscale hostname; override with HERMES_SSH_HOST.
target="${HERMES_SSH_HOST:-deploy@hermes-cloud}"
remote_path="${HERMES_REMOTE_COOKIES_DIR:-/home/deploy/hermes/data/cookies}"

echo ""
echo "→ Uploading $file to $target:$remote_path/"
ssh "$target" "mkdir -p $remote_path"
scp "$file" "$target:$remote_path/$(basename "$file")"

echo ""
echo "✓ Done. Server should pick up the new cookies on the next crawl."
echo "  Verify with:  ssh $target 'ls -la $remote_path/'"
