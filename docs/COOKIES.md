# Cookies (login sessions) skill

The crawlers (Facebook today, more later) need a logged-in session to scrape
behind-the-login content. This doc is the **protocol** the agent and user
follow when cookies are missing or expired.

## Where cookies live

| Site | File on server |
|---|---|
| Facebook | `/data/cookies/fb_cookies.json` (mapped to `~/hermes/data/cookies/fb_cookies.json` on the host) |

Format: Playwright `storage_state` (`{"cookies": [...], "origins": [...]}`).
The crawler loads this directly via `browser.new_context(storage_state=…)`.

## When the agent should ask for a refresh

- `cookie_status` tool reports `present=false` → first-time setup needed
- `cookie_status` reports `age_days > 14` OR `validate_cookies` returns `valid=false` → expired
- A crawler run returns no listings AND `validate_cookies` says invalid

The agent should send `cookie_refresh_instructions(site)` output verbatim to
the user — don't paraphrase, the steps are exact.

## Path A — From your Mac (recommended)

Requires Playwright on the Mac (one-time):

```bash
pip3 install playwright && playwright install chromium
```

Then to refresh Facebook:

```bash
cd ~/1Projects/personal-assistant-cloud
./scripts/sync-cookies.sh facebook
```

What happens:

1. Headed Chromium opens on your Mac, navigates to `facebook.com/login`
2. You sign in normally (handle 2FA / captchas in the real browser)
3. Press Enter in the terminal once you're logged in
4. Playwright writes `data/cookies/fb_cookies.json` locally
5. The script `scp`s it to `deploy@hermes-cloud:~/hermes/data/cookies/` over Tailscale
6. The crawler picks it up on the next run

Set `HERMES_SSH_HOST=deploy@<other-name>` to override the Tailscale target.

## Path B — From another device (iPhone, iPad, etc.)

Use this when you don't have Playwright handy. **No SCP required** — you paste
cookies into Matrix chat and the bot saves them.

1. On the device, sign in to the site in your normal browser
2. Install a "Cookie-Editor" extension
   - Safari iOS: "Cookie-Editor" (TopSec Apps)
   - Chrome/Firefox: "Cookie-Editor" or "EditThisCookie"
3. With the site open, click the extension → **Export** → **JSON**
4. Copy the JSON
5. In your Hermes Matrix room, send a message like:
   ```
   here are my facebook cookies: <paste JSON>
   ```
   The agent calls `import_cookies_paste(site="facebook", json_text=…)` to save it.

The agent auto-detects the format (Playwright storage_state vs Cookie-Editor
array) and normalizes before writing.

## Path C — Browser-in-Tailscale (deferred)

A `linuxserver/chromium` container could be added so you sign in via a full
web desktop reached over Tailscale. Skipped in MVP because Path A + Path B
cover most cases without adding a 300 MB container. See task #39.

## Verifying

```bash
ssh deploy@hermes-cloud 'ls -la ~/hermes/data/cookies/'
```

Then in Matrix ask the bot: `validate facebook cookies` — it'll probe the
site and report whether the session is still active.

## Rotation cadence

- Facebook sessions: typically last 60-90 days, can expire sooner if you log
  in from new devices
- The `cookie_watch` job runs every 12h, flags anything > 14 days as suspect,
  and pings the configured Matrix room with refresh instructions

## Adding a new site

Edit `app/skills/cookies.py` → `SITE_CONFIG` and add:

```python
"newsite": {
    "filename": "newsite_cookies.json",
    "login_url": "https://newsite.com/login",
    "check_url": "https://newsite.com/account",
    "logged_in_signal": "Log Out",   # something only present when authenticated
},
```

Then `scripts/save-cookies.py` and `scripts/sync-cookies.sh` will pick it up
automatically (after you also map the filename in `sync-cookies.sh`'s case
statement).
