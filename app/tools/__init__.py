from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)

# Safety zones
GREEN = "green"   # Auto-allowed: read, navigate, scroll, search
YELLOW = "yellow"  # Log + proceed: click, write files
RED = "red"        # Blocked: submit, send, pay, post

# Red-zone element text patterns
RED_ZONE_PATTERNS = re.compile(
    r"\b(send|submit|post|publish|pay|purchase|confirm|order|buy|checkout|delete|remove|unsubscribe)\b",
    re.IGNORECASE,
)

# Blocked URL schemes
BLOCKED_URL_SCHEMES = ("javascript:", "file:", "data:")
BLOCKED_URL_HOSTS = re.compile(r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)")

ALLOWED_WRITE_PATHS = ("/data", "/tmp", "/obsidian")


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[str]]
    safety: str = GREEN
    admin_only: bool = False


@dataclass
class ToolContext:
    browser: Any = None
    browser_page: Any = None
    room_id: str = ""
    is_admin: bool = False
    matrix_client: Any = None
    cl_crawler: Any = None
    crawl_callback: Any = None
    sender: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        safety: str = GREEN,
        admin_only: bool = False,
    ):
        """Decorator factory to register a tool."""
        def decorator(fn: Callable[..., Awaitable[str]]):
            self._tools[name] = ToolDef(
                name=name,
                description=description,
                parameters=parameters,
                handler=fn,
                safety=safety,
                admin_only=admin_only,
            )
            return fn
        return decorator

    def get_openai_tools(self, is_admin: bool = False) -> list[dict]:
        """Return tool schemas in OpenAI function-calling format."""
        tools = []
        for t in self._tools.values():
            if t.admin_only and not is_admin:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return tools

    async def execute(self, name: str, arguments: dict, context: ToolContext) -> str:
        """Execute a tool by name with safety checks."""
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"success": False, "error": "unknown_tool", "reason": f"Tool '{name}' not found"})

        if tool.admin_only and not context.is_admin:
            return json.dumps({"success": False, "error": "forbidden", "reason": "This tool is only available in the admin room"})

        if tool.safety == RED:
            return json.dumps({"success": False, "error": "blocked", "reason": "This action is blocked by safety policy"})

        try:
            result = await tool.handler(context=context, **arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            log.error(f"Tool {name} failed: {e}", exc_info=True)
            return json.dumps({"success": False, "error": "execution_error", "reason": str(e), "retry": True})


def validate_url(url: str) -> str | None:
    """Return error message if URL is blocked, None if OK."""
    for scheme in BLOCKED_URL_SCHEMES:
        if url.lower().startswith(scheme):
            return f"Blocked URL scheme: {scheme}"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname and BLOCKED_URL_HOSTS.match(parsed.hostname):
            return f"Blocked: internal network address"
    except Exception:
        pass
    return None


def validate_path(path: str) -> str | None:
    """Return error message if path is outside allowed dirs, None if OK."""
    resolved = os.path.realpath(path)
    for prefix in ALLOWED_WRITE_PATHS:
        if resolved.startswith(prefix):
            return None
    return f"Path not allowed. Only {', '.join(ALLOWED_WRITE_PATHS)} are accessible."


def is_red_zone_element(text: str) -> bool:
    """Check if element text matches dangerous action patterns."""
    return bool(RED_ZONE_PATTERNS.search(text))


# Global registry instance
registry = ToolRegistry()
