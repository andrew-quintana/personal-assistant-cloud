"""Cookie watch job — periodically check cookie health, ping user if stale.

Scheduled by main.py (default: every 12h). Sends a short Matrix message to
the admin/apartment room if any site's cookies are missing or look invalid.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.skills import cookies as cookie_skill

log = logging.getLogger(__name__)

USER_ROOM = (
    os.environ.get("COOKIES_NOTIFY_ROOM")
    or os.environ.get("APARTMENT_UPDATE_ROOM")
    or os.environ.get("MATRIX_ADMIN_ROOM", "")
)

# After this many days, even a present cookie file is treated as suspect.
STALE_AFTER_DAYS = int(os.environ.get("COOKIES_STALE_DAYS", "14"))


async def run(browser=None, matrix_client=None) -> dict:
    """Check all known sites' cookie health.

    Args:
        browser: optional Playwright Browser — if given, validates by probing.
                 If omitted, only checks presence + age (no network probe).
        matrix_client: optional matrix-nio AsyncClient — if given + the user
                       has a notification room configured, posts a summary
                       when issues are found.
    """
    issues: list[str] = []
    statuses = cookie_skill.all_status()
    for s in statuses:
        if not s.present:
            issues.append(f"❌ {s.site}: no cookie file")
            continue
        if s.age_days is not None and s.age_days > STALE_AFTER_DAYS:
            issues.append(f"⏱️ {s.site}: {s.age_days:.0f}d old — likely expired")
            continue
        if browser is not None:
            try:
                validated = await cookie_skill.validate(s.site, browser)
                # propagate so callers see the truth in to_dict()
                s.valid = validated.valid
                s.reason = validated.reason
                s.last_valid_check = validated.last_valid_check
                if validated.valid is False:
                    issues.append(f"❌ {s.site}: invalid ({validated.reason})")
            except Exception as e:
                log.warning("cookie validate raised: %s", e)

    if issues:
        log.info("cookie_watch: %d issues found", len(issues))
        if matrix_client and USER_ROOM:
            today = datetime.now(timezone.utc).date().isoformat()
            lines = [f"🍪 **Cookie check — {today}**", ""]
            lines.extend(issues)
            lines.append("")
            for s in statuses:
                if not s.present or (s.age_days is not None and s.age_days > STALE_AFTER_DAYS):
                    lines.append("")
                    lines.append(cookie_skill.refresh_instructions(s.site))
                    break  # one instruction block at a time keeps the message short
            body = "\n".join(lines)
            try:
                await matrix_client.room_send(
                    USER_ROOM,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": body},
                )
            except Exception as e:
                log.error("failed to post cookie alert: %s", e)
    else:
        log.info("cookie_watch: all sites healthy")

    return {
        "checked": len(statuses),
        "issues": len(issues),
        "statuses": [s.to_dict() for s in statuses],
    }
