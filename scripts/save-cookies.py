#!/usr/bin/env python3
"""Open a browser on your Mac, let you log in, then save a Playwright
storage_state file for the agent.

Usage:
    python3 scripts/save-cookies.py facebook
    python3 scripts/save-cookies.py gmail

Output: data/cookies/<site>_cookies.json (relative to repo root)

Pair with scripts/sync-cookies.sh which runs this AND scps the result
to the cloud server over Tailscale.
"""
from __future__ import annotations

import os
import sys

SITES = {
    "facebook": {
        "url": "https://www.facebook.com/login",
        "output": "data/cookies/fb_cookies.json",
    },
    "gmail": {
        "url": "https://accounts.google.com/signin",
        "output": "data/cookies/gmail_cookies.json",
    },
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in SITES:
        print(f"Usage: python3 {sys.argv[0]} <{'|'.join(SITES.keys())}>", file=sys.stderr)
        return 1

    site_key = sys.argv[1]
    site = SITES[site_key]
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output = os.path.join(repo_root, site["output"])
    os.makedirs(os.path.dirname(output), exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print("  pip3 install playwright && playwright install chromium")
        return 1

    print(f"\n→ Opening browser for {site_key}…")
    print("→ Log in normally, then come back here and press Enter.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(site["url"])
        input("\n>>> Press Enter after you've logged in successfully… ")
        context.storage_state(path=output)
        browser.close()

    print(f"\n✓ Cookies saved to: {output}")
    print("→ Now run: scripts/sync-cookies.sh", site_key, "  (to upload to the server)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
