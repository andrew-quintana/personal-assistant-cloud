"""Web search via the Brave Search API.

Returns top results (URL + title + snippet) for the agent to reason over
or hand off to the browser tools for full-page extraction.

Independent index, privacy-aligned, pay-as-you-go. Free tier: 2 000 queries/mo.
Docs: https://api.search.brave.com/app/documentation/web-search/get-started
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from app.tools import registry, ToolContext

log = logging.getLogger(__name__)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


@registry.register(
    name="web_search",
    description=(
        "Search the web via Brave Search. Use this for general questions, current "
        "events, fact-checking, finding articles/listings outside the housing crawlers, "
        "and any time you need information from the open web. Returns up to N results, "
        "each with title, URL, and a short snippet. To read the full content of any "
        "result, follow up with the browser tools."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query. Plain natural language is fine.",
            },
            "count": {
                "type": "integer",
                "description": "How many results to return (1-10). Default 5.",
            },
            "freshness": {
                "type": "string",
                "enum": ["pd", "pw", "pm", "py"],
                "description": (
                    "Recency filter: pd=past day, pw=past week, pm=past month, py=past year. "
                    "Omit for any time."
                ),
            },
        },
        "required": ["query"],
    },
)
async def web_search(
    context: ToolContext,
    query: str,
    count: int = 5,
    freshness: str | None = None,
) -> str:
    if not BRAVE_API_KEY:
        return json.dumps({
            "success": False,
            "error": "config",
            "reason": "BRAVE_API_KEY not set on the server",
        })

    count = max(1, min(int(count or 5), 10))
    params: dict = {"q": query, "count": count, "safesearch": "moderate"}
    if freshness:
        params["freshness"] = freshness

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(BRAVE_API_URL, params=params, headers=headers)
    except httpx.HTTPError as e:
        log.error("Brave search HTTP error: %s", e)
        return json.dumps({"success": False, "error": "http", "reason": str(e), "retry": True})

    if resp.status_code != 200:
        log.warning("Brave search non-200: %s %s", resp.status_code, resp.text[:200])
        return json.dumps({
            "success": False,
            "error": "api",
            "reason": f"Brave API returned {resp.status_code}",
        })

    data = resp.json()
    raw = (data.get("web") or {}).get("results") or []
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("description", ""),
            "age": r.get("age", ""),
        }
        for r in raw[:count]
    ]
    log.info("web_search query=%r results=%d", query[:80], len(results))
    return json.dumps({"success": True, "result": results})
