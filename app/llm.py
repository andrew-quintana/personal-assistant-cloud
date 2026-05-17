from __future__ import annotations
import json
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

API_URL = os.environ.get("LLM_API_URL", "https://api.minimax.io/v1/chat/completions")
API_KEY = os.environ.get("MINIMAX_TOKEN_PLAN_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "MiniMax-M2.5")

_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from MiniMax output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> dict:
    """Call MiniMax chat completions API with optional tool definitions.

    Returns the raw API response dict.
    Raises on HTTP errors.
    """
    payload: dict = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    log.debug(f"LLM request: {len(messages)} messages, {len(tools or [])} tools")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(API_URL, headers=_HEADERS, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Log token usage
    usage = data.get("usage", {})
    log.info(f"LLM tokens: prompt={usage.get('prompt_tokens', '?')} completion={usage.get('completion_tokens', '?')}")

    return data
