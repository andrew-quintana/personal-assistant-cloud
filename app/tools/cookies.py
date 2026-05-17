"""Agent-facing tools for cookie management. Admin-only.

Lets the agent (via Matrix chat) report on cookie state and accept pasted
cookie JSON from the user. The user-facing protocol is documented in
`docs/COOKIES.md`.
"""
from __future__ import annotations

import json
import logging

from app.skills import cookies as cookie_skill
from app.tools import registry, ToolContext, YELLOW

log = logging.getLogger(__name__)


@registry.register(
    name="cookie_status",
    description=(
        "Report which sites have saved cookies, their age, and whether they look usable. "
        "Use this when the user asks about login state, account access, or why a crawler "
        "is failing. Returns JSON with one entry per known site."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)
async def cookie_status(context: ToolContext) -> str:
    statuses = [s.to_dict() for s in cookie_skill.all_status()]
    return json.dumps({"success": True, "result": statuses})


@registry.register(
    name="import_cookies_paste",
    description=(
        "Accept cookie JSON pasted by the user in chat and save it for a site. "
        "Accepts either Playwright storage_state JSON ({'cookies': [...]}) or a "
        "browser-extension export (a bare array of cookies, like Cookie-Editor produces). "
        "Use this when the user pastes JSON in chat after asking how to upload cookies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "site": {
                "type": "string",
                "description": "Lowercase site key, e.g. 'facebook'.",
            },
            "json_text": {
                "type": "string",
                "description": "The raw JSON the user pasted. Pass through verbatim.",
            },
        },
        "required": ["site", "json_text"],
    },
    safety=YELLOW,
    admin_only=True,
)
async def import_cookies_paste(context: ToolContext, site: str, json_text: str) -> str:
    result = cookie_skill.import_cookies(site, json_text)
    if not result.get("ok"):
        return json.dumps({"success": False, "error": result.get("error", "unknown")})
    return json.dumps({
        "success": True,
        "result": (
            f"Saved {result['cookies']} cookies for {site} "
            f"(detected format: {result['source_format']}). "
            f"Stored at {result['path']}."
        ),
    })


@registry.register(
    name="cookie_refresh_instructions",
    description=(
        "Get the user-friendly markdown instructions for refreshing cookies for a site. "
        "Use this when cookies are missing/expired and you need to tell the user how to "
        "provide new ones. Send the returned text as your reply."
    ),
    parameters={
        "type": "object",
        "properties": {
            "site": {"type": "string", "description": "Lowercase site key, e.g. 'facebook'."},
        },
        "required": ["site"],
    },
)
async def cookie_refresh_instructions(context: ToolContext, site: str) -> str:
    return json.dumps({"success": True, "result": cookie_skill.refresh_instructions(site)})


@registry.register(
    name="validate_cookies",
    description=(
        "Probe whether a saved session for a site is still logged in by visiting "
        "the site with Playwright. Returns validity + a short reason. Use when the "
        "user reports the crawler is failing or when they ask 'are my cookies still good?'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "site": {"type": "string", "description": "Lowercase site key, e.g. 'facebook'."},
        },
        "required": ["site"],
    },
)
async def validate_cookies(context: ToolContext, site: str) -> str:
    if not context.browser:
        return json.dumps({"success": False, "error": "browser not available"})
    status = await cookie_skill.validate(site, context.browser)
    return json.dumps({"success": True, "result": status.to_dict()})
