"""Cookie skill — manage per-site browser sessions for the crawlers.

The crawlers (currently Facebook, eventually others) need a logged-in session
to scrape behind-the-login content. This module is the single source of truth
for cookie state: where they live, how to import them from various export
formats, and how to validate that the saved session still works.

Read `docs/COOKIES.md` for the user-facing protocol the agent should follow.

Two cookie formats are accepted on import:
1. **Playwright `storage_state`** — what `scripts/save-cookies.py` produces.
   Shape: `{"cookies": [...], "origins": [...]}`. Used as-is.
2. **Cookie-Editor / EditThisCookie export** — an array of cookies.
   Shape: `[{"name": ..., "value": ..., "domain": ..., ...}]`. We convert to
   storage_state by wrapping under `cookies`.

After import the file lives at `/data/cookies/<site>_cookies.json` in
Playwright storage_state format, ready for `browser.new_context(storage_state=...)`.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

COOKIES_DIR = Path(os.environ.get("COOKIES_DIR", "/data/cookies"))

# Per-site config. Add entries as new crawlers grow.
SITE_CONFIG: dict[str, dict[str, str]] = {
    "facebook": {
        "filename": "fb_cookies.json",
        "login_url": "https://www.facebook.com/login",
        "check_url": "https://www.facebook.com/",
        "logged_in_signal": "facebook.com/messages",  # link only shown when logged in
    },
    # Future sites go here, e.g.:
    # "gmail": {...},
}


@dataclass
class CookieStatus:
    site: str
    present: bool
    path: Path
    age_days: float | None
    last_valid_check: float | None
    valid: bool | None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "present": self.present,
            "path": str(self.path),
            "age_days": round(self.age_days, 2) if self.age_days is not None else None,
            "valid": self.valid,
            "reason": self.reason,
        }


def _ensure_dir() -> None:
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)


def cookie_path(site: str) -> Path:
    """Canonical path for a site's storage_state file."""
    cfg = SITE_CONFIG.get(site)
    if not cfg:
        raise ValueError(f"Unknown site: {site}. Add to SITE_CONFIG in app/skills/cookies.py.")
    return COOKIES_DIR / cfg["filename"]


def get_status(site: str) -> CookieStatus:
    """Return basic on-disk status (no network check)."""
    path = cookie_path(site)
    if not path.exists():
        return CookieStatus(site=site, present=False, path=path,
                             age_days=None, last_valid_check=None,
                             valid=None, reason="file not present")
    age_seconds = time.time() - path.stat().st_mtime
    return CookieStatus(
        site=site,
        present=True,
        path=path,
        age_days=age_seconds / 86400,
        last_valid_check=None,
        valid=None,
        reason="",
    )


def all_status() -> list[CookieStatus]:
    return [get_status(s) for s in SITE_CONFIG]


# ---------------------------------------------------------------------------
# Import — accept various export formats and write canonical storage_state.
# ---------------------------------------------------------------------------
def _looks_like_storage_state(obj: Any) -> bool:
    return isinstance(obj, dict) and "cookies" in obj and isinstance(obj["cookies"], list)


def _looks_like_extension_export(obj: Any) -> bool:
    """Cookie-Editor / EditThisCookie produce a bare array of cookies."""
    if not isinstance(obj, list) or not obj:
        return False
    return isinstance(obj[0], dict) and "name" in obj[0] and "domain" in obj[0]


def _normalize_extension_cookie(c: dict) -> dict:
    """Make a Cookie-Editor cookie look like a Playwright cookie."""
    out = {
        "name": c["name"],
        "value": c.get("value", ""),
        "domain": c.get("domain", ""),
        "path": c.get("path", "/"),
        "httpOnly": bool(c.get("httpOnly", False)),
        "secure": bool(c.get("secure", False)),
        "sameSite": c.get("sameSite", "Lax").capitalize() if c.get("sameSite") else "Lax",
    }
    if "expirationDate" in c:
        out["expires"] = int(c["expirationDate"])
    elif "expires" in c:
        try:
            out["expires"] = int(c["expires"])
        except (TypeError, ValueError):
            pass
    return out


def import_cookies(site: str, raw_text: str) -> dict:
    """Accept either Playwright storage_state JSON or a browser-extension
    JSON export. Write the canonical storage_state file. Returns a small
    summary dict.
    """
    if site not in SITE_CONFIG:
        return {"ok": False, "error": f"unknown site '{site}'"}

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"input is not valid JSON ({e})"}

    if _looks_like_storage_state(parsed):
        storage_state = parsed
        source_format = "playwright_storage_state"
    elif _looks_like_extension_export(parsed):
        storage_state = {
            "cookies": [_normalize_extension_cookie(c) for c in parsed],
            "origins": [],
        }
        source_format = "extension_export"
    else:
        return {"ok": False, "error": (
            "unrecognised shape. Expected Playwright storage_state "
            '({"cookies":[...]}) or a bare array of cookies from a '
            "browser extension export."
        )}

    _ensure_dir()
    path = cookie_path(site)
    path.write_text(json.dumps(storage_state, indent=2))
    log.info(
        "cookies: imported %s for %s (%d cookies, format=%s)",
        path.name, site, len(storage_state["cookies"]), source_format,
    )
    return {
        "ok": True,
        "path": str(path),
        "cookies": len(storage_state["cookies"]),
        "source_format": source_format,
    }


# ---------------------------------------------------------------------------
# Validate — open the saved session in Playwright and probe.
# ---------------------------------------------------------------------------
async def validate(site: str, browser) -> CookieStatus:
    """Visit the site's check_url and look for a logged-in signal.

    `browser` must be a Playwright Browser instance (already launched).
    """
    status = get_status(site)
    if not status.present:
        status.valid = False
        status.reason = "no cookie file"
        return status

    cfg = SITE_CONFIG[site]
    try:
        context = await browser.new_context(storage_state=str(status.path))
        page = await context.new_page()
        await page.goto(cfg["check_url"], wait_until="domcontentloaded", timeout=20000)
        html = await page.content()
        await context.close()
    except Exception as e:
        status.valid = False
        status.reason = f"probe error: {e!s}"
        return status

    if cfg["logged_in_signal"] in html:
        status.valid = True
        status.reason = "logged-in signal found"
    else:
        status.valid = False
        status.reason = f"logged-in signal '{cfg['logged_in_signal']}' not found"
    status.last_valid_check = time.time()
    return status


# ---------------------------------------------------------------------------
# Refresh instructions — what to tell the user.
# ---------------------------------------------------------------------------
SCP_TARGET_DIR = "/home/deploy/hermes/data/cookies"


def refresh_instructions(site: str) -> str:
    """Return a short markdown instruction block the agent can send in Matrix."""
    cfg = SITE_CONFIG.get(site)
    if not cfg:
        return f"Unknown site '{site}'."
    filename = cfg["filename"]
    return (
        f"**{site.title()} cookies need a refresh.**\n\n"
        "Two paths — pick whichever is easier:\n\n"
        "**A. From your Mac (recommended; uses Playwright):**\n"
        "```bash\n"
        "cd ~/1Projects/personal-assistant-cloud\n"
        f"./scripts/sync-cookies.sh {site}\n"
        "```\n"
        "It opens a browser, you sign in, then it scps the saved session over Tailscale.\n\n"
        "**B. From a phone / iPad (no Playwright):**\n"
        f"1. Sign in to {site} in your mobile browser.\n"
        '2. Install a "Cookie-Editor" extension (Safari, Chrome, etc.).\n'
        f"3. Open {site}, click the extension → **Export** → JSON.\n"
        "4. Paste the JSON in this chat and prefix it with: "
        f"`/import-cookies {site}` (or message me asking to save them).\n\n"
        f"Either way the file ends up at `{SCP_TARGET_DIR}/{filename}` "
        "on the server."
    )
