#!/usr/bin/env bash
#
# One-time server bootstrap for hermes-agent on a fresh VPS (Hetzner CX22+).
#
# Run as root on the freshly-provisioned box. It will:
#   1. Update apt + install Docker
#   2. Create a `deploy` user with sudo + Docker access
#   3. Copy your SSH key from root to deploy
#   4. Set up a bare git repo at /home/deploy/hermes.git
#   5. Install a post-receive hook that checks out into /home/deploy/hermes
#      and runs `docker compose up --build -d` after every push
#   6. Lock down ufw (Tailscale port + SSH only)
#
# Usage (on the server, as root):
#   curl -fsSL <this-script-url> | bash
# Or copy this file over and run it locally:
#   scp deploy/setup-server.sh root@<server>:
#   ssh root@<server> bash setup-server.sh
#
# After this completes, from your laptop:
#   git remote add prod ssh://deploy@<server>/home/deploy/hermes.git
#   git push prod main
#
# That triggers a build + restart on the server.

set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
BARE_REPO="${DEPLOY_HOME}/hermes.git"
WORK_DIR="${DEPLOY_HOME}/hermes"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

echo "==> 1/6  apt update + Docker"
apt-get update -y
apt-get upgrade -y
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> 2/6  Create ${DEPLOY_USER} user"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
usermod -aG sudo "${DEPLOY_USER}"
# Passwordless sudo for the deploy user
echo "${DEPLOY_USER} ALL=(ALL) NOPASSWD: ALL" >/etc/sudoers.d/${DEPLOY_USER}
chmod 0440 /etc/sudoers.d/${DEPLOY_USER}

echo "==> 3/6  Copy SSH keys"
mkdir -p "${DEPLOY_HOME}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  cp /root/.ssh/authorized_keys "${DEPLOY_HOME}/.ssh/authorized_keys"
fi
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_HOME}/.ssh"
chmod 700 "${DEPLOY_HOME}/.ssh"
chmod 600 "${DEPLOY_HOME}/.ssh/authorized_keys" 2>/dev/null || true

echo "==> 4/6  Bare git repo at ${BARE_REPO}"
sudo -u "${DEPLOY_USER}" mkdir -p "${BARE_REPO}" "${WORK_DIR}"
sudo -u "${DEPLOY_USER}" git -C "${BARE_REPO}" init --bare --initial-branch=main

echo "==> 5/6  post-receive hook"
HOOK="${BARE_REPO}/hooks/post-receive"
cat >"${HOOK}" <<HOOK_EOF
#!/usr/bin/env bash
# Auto-deploy hook. Checks out the pushed tree into ${WORK_DIR} and
# runs docker compose up -d --build.
set -euo pipefail

WORK_DIR="${WORK_DIR}"
BARE_REPO="${BARE_REPO}"

while read -r oldrev newrev refname; do
  branch="\${refname##refs/heads/}"
  if [[ "\$branch" != "main" ]]; then
    echo "[hook] Skipping non-main branch: \$branch"
    continue
  fi
  echo "[hook] Deploying \$branch (\$newrev)..."
  git --work-tree="\$WORK_DIR" --git-dir="\$BARE_REPO" checkout -f "\$branch"
done

cd "\$WORK_DIR"

if [[ ! -f .env ]]; then
  echo "[hook] WARNING: no .env on server yet. Copy .env.example to .env and fill in." >&2
  echo "[hook] Skipping docker compose until .env exists." >&2
  exit 0
fi

echo "[hook] docker compose up -d --build"
docker compose up -d --build
docker compose ps
HOOK_EOF
chmod +x "${HOOK}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${HOOK}"

echo "==> 6/6  Firewall (ufw)"
if command -v ufw >/dev/null 2>&1; then
  ufw --force default deny incoming
  ufw default allow outgoing
  ufw allow 41641/udp comment "Tailscale"
  ufw allow 22/tcp     comment "SSH (drop after tailscale ssh works)"
  ufw --force enable
fi

cat <<DONE

==============================================================
Done. From your laptop:

  git remote add prod ssh://${DEPLOY_USER}@<server-ip>/home/${DEPLOY_USER}/hermes.git
  git push prod main

Then SSH in once to create .env:

  ssh ${DEPLOY_USER}@<server-ip>
  cd ~/hermes
  cp .env.example .env
  nano .env       # fill in TS_AUTHKEY, MATRIX_BOT_PASSWORD, etc.
  docker compose up -d --build

After that, subsequent \`git push prod main\` deploys automatically via
the post-receive hook. Once Tailscale is up, you can use \`tailscale ssh\`
and drop port 22 from ufw.
==============================================================
DONE
