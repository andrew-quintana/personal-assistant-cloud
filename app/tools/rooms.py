from __future__ import annotations
import json
import os

from app.tools import registry, ToolContext

ADMIN_ROOM = os.environ.get("MATRIX_ADMIN_ROOM", "")


@registry.register(
    name="create_room",
    description="Create a new Matrix chat room and invite the requesting user.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name for the new room"},
        },
        "required": ["name"],
    },
    admin_only=True,
)
async def create_room(context: ToolContext, name: str) -> str:
    from nio import RoomCreateResponse
    resp = await context.matrix_client.room_create(
        name=name,
        invite=[context.sender] if context.sender else [],
    )
    if isinstance(resp, RoomCreateResponse):
        return json.dumps({"success": True, "result": f"Room '{name}' created (ID: {resp.room_id}). Invite sent."})
    return json.dumps({"success": False, "error": "create_failed", "reason": str(resp)})


@registry.register(
    name="list_rooms",
    description="List all Matrix rooms the bot is currently in.",
    parameters={"type": "object", "properties": {}, "required": []},
    admin_only=True,
)
async def list_rooms(context: ToolContext) -> str:
    rooms = context.matrix_client.rooms
    if not rooms:
        return json.dumps({"success": True, "result": "Not in any rooms."})
    result = []
    for rid, r in rooms.items():
        entry = {
            "name": r.display_name or rid,
            "room_id": rid,
            "members": r.member_count,
        }
        if rid == ADMIN_ROOM:
            entry["admin"] = True
        result.append(entry)
    return json.dumps({"success": True, "result": result})
