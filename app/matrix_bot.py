from __future__ import annotations
import asyncio
import logging
import os
import re
from urllib.parse import quote

import httpx
from nio import AsyncClient, InviteMemberEvent, MatrixRoom, RoomMessageText, LoginResponse

from app.agent import AgentLoop

log = logging.getLogger(__name__)

HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://conduit:6167")
BOT_USER = os.environ.get("MATRIX_BOT_USER", "@hermes:hermes.local")
BOT_PASSWORD = os.environ.get("MATRIX_BOT_PASSWORD", "")


class HermesBot:
    def __init__(self, agent: AgentLoop):
        self.client = AsyncClient(HOMESERVER, BOT_USER)
        self.agent = agent
        self._running = False

    async def start(self):
        log.info(f"Logging into Matrix as {BOT_USER} at {HOMESERVER}")
        resp = await self.client.login(BOT_PASSWORD)
        if not isinstance(resp, LoginResponse):
            log.error(f"Matrix login failed: {resp}")
            return

        log.info(f"Logged in as {resp.user_id}")

        # Register the invite callback BEFORE initial sync, so any pending
        # invites (delivered as part of initial sync state) get auto-joined.
        self.client.add_event_callback(self._on_invite, InviteMemberEvent)

        # Initial sync — picks up pending invites; old messages flow past
        # without triggering callbacks because the message callback isn't
        # registered yet.
        await self.client.sync(timeout=5000)
        log.info("Initial sync done, now listening for new messages")

        # Now register message callback so only NEW messages trigger us.
        self.client.add_event_callback(self._on_message, RoomMessageText)

        self._running = True
        while self._running:
            try:
                await self.client.sync(timeout=30000)
            except Exception as e:
                log.error(f"Sync error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        self._running = False
        await self.client.close()

    async def _on_invite(self, room: MatrixRoom, event: InviteMemberEvent):
        if event.state_key != self.client.user_id:
            return
        log.info(f"Invited to {room.room_id}, auto-joining")
        # matrix-nio sends an empty body on join; Conduit rejects with
        # "EOF while parsing a value". Call the join endpoint directly
        # with an explicit `{}` body so Conduit's JSON parser is happy.
        url = f"{HOMESERVER}/_matrix/client/v3/rooms/{quote(room.room_id)}/join"
        headers = {"Authorization": f"Bearer {self.client.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=10) as h:
                r = await h.post(url, json={}, headers=headers)
            if r.status_code == 200:
                log.info(f"Joined {room.room_id}")
            else:
                log.error(f"Join failed {r.status_code}: {r.text}")
        except Exception as e:
            log.error(f"Join exception: {e}", exc_info=True)

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText):
        if event.sender == self.client.user_id:
            return

        body = event.body.strip()
        if not body:
            return

        log.info(f"[{room.display_name}] {event.sender}: {body}")

        try:
            # Show typing indicator
            await self.client.room_typing(room.room_id, typing_state=True)

            response = await self.agent.handle_message(
                room_id=room.room_id,
                room_name=room.display_name or room.room_id,
                sender=event.sender,
                message=body,
            )

            await self.client.room_typing(room.room_id, typing_state=False)
            await self._send(room.room_id, response)

        except Exception as e:
            log.error(f"Agent error: {e}", exc_info=True)
            await self.client.room_typing(room.room_id, typing_state=False)
            await self._send(room.room_id, "Sorry, I ran into an error. Please try again.")

    async def _send(self, room_id: str, text: str):
        await self.client.room_send(
            room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": text,
                "format": "org.matrix.custom.html",
                "formatted_body": _md_to_html(text),
            },
        )


def _md_to_html(text: str) -> str:
    html = text
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)
    html = html.replace("\n", "<br>")
    return html
