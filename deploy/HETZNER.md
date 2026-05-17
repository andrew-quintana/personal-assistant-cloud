# Deploying hermes-agent to Hetzner Cloud

Tested on **Hetzner CX22** (4 GB / 2 vCPU / 40 GB SSD, €4.50/mo) running
Ubuntu 24.04 LTS. Same steps work on CX32 (8 GB) for more headroom.

The deployment is **Tailscale-only** (no public ports beyond UDP 41641 for
Tailscale itself) and **GitHub-free** (the server never authenticates with
GitHub — you push directly to a bare git repo over SSH).

## Pre-flight (do these once, offline)

1. **Create a Tailscale auth key.** https://login.tailscale.com/admin/settings/keys
   - Reusable: No, Ephemeral: No
   - Tag the node (`tag:hermes`) so you can manage ACLs
   - Copy the key — you'll paste it into `.env`
2. **Have an LLM API key ready** (Anthropic or OpenAI; see `app/llm.py`).
3. (Optional but recommended) Make sure your laptop's SSH public key is added
   to the Hetzner SSH-keys panel before provisioning.

## Provision the box

```bash
# Hetzner Cloud Console, or hcloud CLI:
hcloud server create \
  --name hermes-cloud \
  --type cx22 \
  --image ubuntu-24.04 \
  --location ash \
  --ssh-key <your-ssh-key-name>
```

Note the public IPv4. Test SSH:

```bash
ssh root@<server-ip>
```

## Bootstrap the server (one-time)

Copy the setup script over and run it:

```bash
scp deploy/setup-server.sh root@<server-ip>:
ssh root@<server-ip> bash setup-server.sh
```

This installs Docker, creates a `deploy` user with passwordless sudo + Docker
access, copies your SSH key to that user, creates a bare git repo at
`/home/deploy/hermes.git`, installs a `post-receive` hook, and locks down ufw
(Tailscale UDP 41641 + SSH only).

## Wire up the git remote and push

On your laptop:

```bash
cd /Users/aq_home/1Projects/personal-assistant-cloud
git remote add prod ssh://deploy@<server-ip>/home/deploy/hermes.git
git push prod main
```

The first push triggers the `post-receive` hook. It checks the code out into
`/home/deploy/hermes` but skips `docker compose` because there's no `.env`
yet (warning printed).

## First-time .env on the server

SSH in once as `deploy` to create `.env`:

```bash
ssh deploy@<server-ip>
cd ~/hermes
cp .env.example .env
nano .env          # fill in TS_AUTHKEY, TS_TAILNET, MATRIX_BOT_PASSWORD, LLM key
docker compose up -d --build
```

Watch logs to confirm startup:

```bash
docker compose logs -f crawler
```

You should see:
- `Logging into Matrix as @hermes-bot:hermes.local`
- `Scheduler started — apartment_daily_update at 08:00 UTC`
- `Application startup complete.`

## First-time Matrix setup

1. From any tailnet-connected device, open
   `https://<TS_HOSTNAME>.<TS_TAILNET>` — Element loads.
2. Register your personal Matrix account.
3. Register the bot account using `MATRIX_BOT_USER` / `MATRIX_BOT_PASSWORD`
   from `.env`.
4. Create a room (e.g. "Apartment Search") and invite the bot.
5. Find the room ID:
   ```bash
   curl http://<TS-IP>:8000/rooms
   ```
6. Set `APARTMENT_UPDATE_ROOM` to that room ID in `.env`.
7. `docker compose up -d crawler` to pick up the new env.

## Subsequent deploys

From your laptop:

```bash
git push prod main
```

The post-receive hook rebuilds + restarts. Logs visible via
`ssh deploy@<server-ip> 'cd ~/hermes && docker compose logs -f crawler'`.

## Install the host watchdog (one-time)

After the first successful deploy, install the cron-based watchdog. It pings
`/health` every 5 min and restarts the crawler if unresponsive.

```bash
ssh deploy@<server-ip> 'cd ~/hermes && ./scripts/install-watchdog.sh'
```

Logs to `/var/log/hermes-watchdog.log`. This is L3 in the resilience model
(see README), behind `autoheal` (L2) which auto-restarts unhealthy containers.

## When something breaks

Recovery scripts in `scripts/`:

| Command | What |
|---|---|
| `./scripts/health.sh` | Snapshot of every container + agent /health + tailscale status |
| `./scripts/repair.sh` | Diagnostic walk-through; flags issues + suggests fixes |
| `./scripts/restart.sh [svc]` | Restart one service or everything |
| `./scripts/logs.sh <svc> [n]` | Tail logs |

Run any over SSH: `ssh deploy@<host> 'cd ~/hermes && ./scripts/health.sh'`.

## Tighten access further (recommended)

Once Tailscale is up and you can `tailscale ssh deploy@hermes-cloud`,
remove port 22 from the firewall:

```bash
sudo ufw delete allow 22/tcp
```

Now the only inbound is UDP 41641 (Tailscale). Everything else — SSH,
git push, Element, the agent HTTP — flows over the tailnet.

## Daily job

The apartment-search job runs automatically at `APARTMENT_DAILY_CRON_HOUR`
UTC (default 08:00 = 01:00 PT).

Trigger immediately for testing:

```bash
curl -X POST http://<TS-IP>:8000/jobs/apartment-search/run
```

## Vault syncing

The agent writes to the `obsidian-vault` Docker volume mounted at `/obsidian`.
To get those files onto your phone/Mac:

- **Option A (recommended):** add a `linuxserver/obsidian` service to the
  compose that opens the same volume; log in to Obsidian Sync once inside it.
  Obsidian Sync propagates to all your devices.
- **Option B:** add a Syncthing service that shares the volume with your Mac.

Neither is in the repo by default — keep the cloud surface area minimal.

## Backups

Two stateful Docker volumes:
- `conduit-data` — Matrix history
- `crawler-data` — listings DB
- `obsidian-vault` — agent-written vault content

Snapshot regularly:

```bash
docker run --rm \
  -v conduit-data:/src:ro \
  -v "$(pwd)/backups":/dst \
  alpine tar czf /dst/conduit-$(date +%F).tgz -C /src .
```

Or use Hetzner's volume snapshots.
