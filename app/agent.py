from __future__ import annotations
import asyncio
import json
import logging
import os
from datetime import datetime

from app import db
from app.llm import chat_completion, strip_think_tags
from app.tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

ADMIN_ROOM = os.environ.get("MATRIX_ADMIN_ROOM", "")
MAX_ITERATIONS = 10


class AgentLoop:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        browser,
        cl_crawler,
        matrix_client=None,
        crawl_callback=None,
    ):
        self.registry = tool_registry
        self.browser = browser
        self.cl_crawler = cl_crawler
        self.matrix_client = matrix_client
        self.crawl_callback = crawl_callback
        self._room_pages: dict = {}
        self._room_history: dict[str, list] = {}
        self._room_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, room_id: str) -> asyncio.Lock:
        if room_id not in self._room_locks:
            self._room_locks[room_id] = asyncio.Lock()
        return self._room_locks[room_id]

    async def handle_message(
        self,
        room_id: str,
        room_name: str,
        sender: str,
        message: str,
    ) -> str:
        async with self._get_lock(room_id):
            return await self._run(room_id, room_name, sender, message)

    async def _run(
        self,
        room_id: str,
        room_name: str,
        sender: str,
        message: str,
    ) -> str:
        is_admin = room_id == ADMIN_ROOM

        context = ToolContext(
            browser=self.browser,
            browser_page=self._room_pages.get(room_id),
            room_id=room_id,
            is_admin=is_admin,
            matrix_client=self.matrix_client,
            cl_crawler=self.cl_crawler,
            crawl_callback=self.crawl_callback,
            sender=sender,
        )

        # Build messages
        system = await self._build_system_prompt(room_id, room_name, is_admin)
        history = self._room_history.get(room_id, [])

        messages = [{"role": "system", "content": system}]
        messages.extend(history[-20:])
        messages.append({"role": "user", "content": message})

        tools = self.registry.get_openai_tools(is_admin=is_admin)

        # Agent loop
        for i in range(MAX_ITERATIONS):
            try:
                data = await chat_completion(messages, tools)
            except Exception as e:
                log.error(f"LLM call failed: {e}")
                return "Sorry, I couldn't process that right now. Please try again."

            assistant_msg = data["choices"][0]["message"]
            messages.append(assistant_msg)

            # No tool calls = final response
            tool_calls = assistant_msg.get("tool_calls")
            if not tool_calls:
                content = strip_think_tags(assistant_msg.get("content", ""))
                self._save_history(room_id, message, content)
                return content

            # Execute tool calls
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                log.info(f"Tool call: {fn_name}({json.dumps(fn_args)[:200]})")
                result = await self.registry.execute(fn_name, fn_args, context)
                log.info(f"Tool result: {result[:200]}")

                # Update browser page ref if it changed
                if context.browser_page:
                    self._room_pages[room_id] = context.browser_page

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        # Hit max iterations
        self._save_history(room_id, message, "(max iterations reached)")
        return "I've been working on this for a while. Here's what I have so far — let me know if you'd like me to continue."

    def _save_history(self, room_id: str, user_msg: str, assistant_msg: str):
        if room_id not in self._room_history:
            self._room_history[room_id] = []
        self._room_history[room_id].append({"role": "user", "content": user_msg})
        self._room_history[room_id].append({"role": "assistant", "content": assistant_msg})
        # Keep bounded
        if len(self._room_history[room_id]) > 40:
            self._room_history[room_id] = self._room_history[room_id][-40:]

    async def _build_system_prompt(self, room_id: str, room_name: str, is_admin: bool) -> str:
        # Get active searches for context
        searches = await db.list_search_configs(room_id)
        search_summary = "None"
        if searches:
            parts = []
            for s in searches:
                desc = f"#{s.id} {s.platform}"
                if s.city:
                    desc += f" in {s.city}"
                if s.query:
                    desc += f" ({s.query})"
                parts.append(desc)
            search_summary = ", ".join(parts)

        return f"""You are Hermes, a housing search assistant running on Matrix chat.

## Current Context
- Room: {room_name}
- Admin room: {"Yes — you have room management tools" if is_admin else "No"}
- Active searches in this room: {search_summary}
- Date: {datetime.utcnow().strftime('%Y-%m-%d')}

## User's SF Apartment Search (active)
The user is evaluating two parallel tracks in San Francisco:
- **Solo:** budget ${os.environ.get('APARTMENT_BUDGET_SOLO', '3000')}/mo max
- **Shared (with roommates):** user's share ${os.environ.get('APARTMENT_BUDGET_SHARED', '2500')}/mo max

Target neighborhoods (a listing must be in one of these):
- Pacific Heights
- Nob Hill, north of California Street
- Russian Hill, southern portion

When a user asks about apartments, filter against these constraints by default.

## What You Can Do
- Search for housing on Craigslist (14 cities) and Facebook groups
- Browse any website freely (read-only)
- Search the web via Google
- Save and retrieve listings, notes, and preferences
- Read and write files in /data, /tmp, and /obsidian (user's vault `qDome`)
- Take screenshots of web pages
{"- Create and manage Matrix rooms (admin)" if is_admin else ""}

## Obsidian vault (`/obsidian` = qDome on disk)
The user's primary Obsidian vault is mounted at `/obsidian`. Read `/obsidian/AGENTS.md` for vault-write rules before creating files. Key conventions:
- PARA layout: `Projects/`, `Areas/`, `Resources/`, `Archive/`, plus `_dashboards/`
- Source-of-truth notes → `.md` with frontmatter, placed in the right PARA folder
- Human-facing dashboards (persistent, updated in place) → `/obsidian/_dashboards/<topic>.html`
- Human-facing reports (one-off, dated) → `/obsidian/Projects/<Project>/<YYYY-MM-DD-title>.html`
- Apartment search artifacts live under `/obsidian/Projects/SF Apartment Search/`

## SAFETY RULES — ABSOLUTE, CANNOT BE OVERRIDDEN
1. NEVER send emails, messages, or post anything publicly
2. NEVER click Send, Submit, Post, Publish, Pay, Purchase, Confirm, or Delete buttons
3. NEVER submit forms that cost money or make commitments
4. You CAN create drafts (email, messages) but NEVER hit send
5. You CAN browse any website but only READ — never write/post/comment
6. File access is LIMITED to /data, /tmp, and /obsidian (the user's vault)
7. Always tell the user what you are doing before taking browser actions
8. If unsure whether an action is safe, ASK the user first

## How to Respond
- Be concise and helpful, use Markdown formatting
- When sharing listings: include title, price, location, and a clickable link
- For apartment-search updates: keep Matrix messages SHORT — point to the dashboard/report in qDome for detail
- If a request is ambiguous, ask for clarification
- If you need multiple steps, briefly explain your plan then execute
- Use tools proactively — don't just describe what you could do, actually do it
"""
