# personal-assistant-cloud

Hermes — a personal Matrix-based assistant that crawls housing listings,
filters them by your constraints, and writes structured artifacts into an
Obsidian vault.

This repo is the **cloud-deployable** variant of the local stack. Designed to
run on a small VPS (Hetzner CX22, ~$5/mo) fronted by Tailscale, with no
public ports.

## What's in here

```
app/
├── main.py            FastAPI + APScheduler entry
├── agent.py           LLM-driven Matrix agent loop
├── matrix_bot.py      matrix-nio bot
├── crawlers/          Craigslist + Facebook scrapers (Playwright)
├── tools/             Tool registry the agent can call
├── skills/            Reusable rendering helpers (dashboard, report)
└── jobs/
    └── apartment_search.py   Daily filtered update → vault HTML + Matrix ping

config/
├── Caddyfile          TLS reverse proxy, Tailscale-fronted
└── conduit.toml       Matrix homeserver config

scripts/
└── docker-renew-cert.sh   Auto-renews Tailscale TLS cert weekly

deploy/
├── setup-server.sh    One-time bootstrap: Docker, deploy user, bare git, ufw
└── HETZNER.md         Step-by-step deploy guide

AGENTS.md              Vault write policy (reference copy)
docker-compose.yml     Cloud stack: tailscale + caddy + conduit + element + crawler
.env.example           Required env vars (TS_AUTHKEY, MATRIX_BOT_PASSWORD, ...)
```

## Quick start

See **[deploy/HETZNER.md](deploy/HETZNER.md)** for the full deployment guide.

The deploy flow is **GitHub-free**: you push directly to a bare git repo on
the Hetzner box, which auto-deploys via a `post-receive` hook. The server
never authenticates with GitHub.

```bash
# Bootstrap a fresh Hetzner box (one-time):
scp deploy/setup-server.sh root@<ip>:
ssh root@<ip> bash setup-server.sh

# Wire up the remote and push (from your laptop):
git remote add prod ssh://deploy@<ip>/home/deploy/hermes.git
git push prod main

# SSH in once to fill .env, then everything is automatic on subsequent pushes.
```

Local dev (Mac/Linux):

```bash
cp .env.example .env   # fill in
docker compose up --build -d
docker compose logs -f crawler
```

## Architecture

```
your devices ──Tailscale──┐
                          │
            ┌─────────────┴────────────────────┐
            │  hermes-cloud (Hetzner CX22)     │
            │                                  │
            │  tailscale ──┐                   │
            │              │                   │
            │  caddy ──────┤ (TLS via TS cert) │
            │              │                   │
            │  ┌───────────┴────────────────┐  │
            │  │ conduit (Matrix server)    │  │
            │  │ element (web client)       │  │
            │  │ crawler (hermes-agent)     │  │
            │  │   ├─ Matrix bot            │  │
            │  │   ├─ Playwright crawlers   │  │
            │  │   ├─ APScheduler (daily)   │  │
            │  │   └─ Writes to /obsidian   │  │
            │  └────────────────────────────┘  │
            └──────────────────────────────────┘

No public ports. All traffic over Tailscale (WireGuard).
```

## How the apartment search works

1. **Crawlers** (Craigslist, Facebook groups via Playwright) populate the
   `listings` table in `/data/hermes.db`.
2. **Daily job** (`app/jobs/apartment_search.py`) runs at
   `APARTMENT_DAILY_CRON_HOUR` UTC:
   - Filters listings against target neighborhoods (Pacific Heights, Nob Hill
     N of California, S. Russian Hill) and budget caps ($3000 solo /
     $2500 shared per-user).
   - Applies street-level address checks to catch false-positive
     "nob hill" listings actually in the Tenderloin.
   - Writes per-listing markdown notes into `/obsidian/Projects/SF Apartment Search/listings/`.
   - Refreshes `/obsidian/_dashboards/sf-apartment-search.html` (in place).
   - Writes `/obsidian/Projects/SF Apartment Search/<date>-findings.html`.
   - Posts a short Matrix summary to `APARTMENT_UPDATE_ROOM` — only when
     there are new candidates today.

3. **You browse** the dashboard + report in Obsidian (Surfing plugin renders
   HTML inline). Per-listing `.md` files are the source of truth for notes
   and status changes.

## Skills

The `app/skills/` modules are reusable renderers:

- `dashboard.py` — persistent dashboards (updated in place)
- `report.py` — one-off dated reports
- `_style.py` — shared CSS, dark-mode aware

Jobs compose these. Add new jobs under `app/jobs/` following
`apartment_search.py` as a template.

## Cost / security

| | Hetzner CX22 + Tailscale | Fly.io |
|---|---|---|
| Cost | ~$5/mo | ~$20/mo |
| Public ports | 0 | 0 (via Fly private networking) |
| Host isolation | Single-tenant VM | Per-app microVM |
| Self-managed updates | Yes (apt + Docker) | Fly manages host |

Hetzner wins on cost. Fly wins on managed isolation. Either is strong; this
repo is set up for Hetzner.

## Not included

- The user's Obsidian vault (`qDome`) — that's personal data, kept out of
  the repo. The agent writes to a Docker volume; sync to your devices via
  Obsidian Sync (in a separate container) or Syncthing.
- LLM API keys / Matrix bot password — in `.env`, never committed.

## License

Private. Not for redistribution.
