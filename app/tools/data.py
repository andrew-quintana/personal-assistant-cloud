from __future__ import annotations
import json

from app import db
from app.models import SearchConfig
from app.tools import registry, ToolContext


@registry.register(
    name="get_listings",
    description="Search saved housing listings from the database. Returns previously crawled listings matching the filters.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["craigslist", "facebook"], "description": "Filter by source platform"},
            "min_price": {"type": "integer", "description": "Minimum price filter"},
            "max_price": {"type": "integer", "description": "Maximum price filter"},
            "limit": {"type": "integer", "description": "Max results to return (default 20)"},
        },
        "required": [],
    },
)
async def get_listings(context: ToolContext, source: str = None, min_price: int = None, max_price: int = None, limit: int = 20) -> str:
    import aiosqlite
    query = "SELECT * FROM listings WHERE 1=1"
    params: list = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if min_price is not None:
        query += " AND price >= ?"
        params.append(min_price)
    if max_price is not None:
        query += " AND price <= ?"
        params.append(max_price)
    query += " ORDER BY crawled_at DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return json.dumps({"success": True, "result": "No listings found matching filters."})

    listings = []
    for r in rows:
        listings.append({
            "title": r["title"],
            "price": r["price"],
            "location": r["location"],
            "url": r["url"],
            "source": r["source"],
        })
    return json.dumps({"success": True, "result": listings})


@registry.register(
    name="get_active_searches",
    description="List all active saved searches. Shows what the bot is monitoring.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def get_active_searches(context: ToolContext) -> str:
    configs = await db.list_search_configs(context.room_id)
    if not configs:
        return json.dumps({"success": True, "result": "No active searches."})
    results = []
    for c in configs:
        entry = {"id": c.id, "platform": c.platform}
        if c.city:
            entry["city"] = c.city
        if c.query:
            entry["section"] = c.query
        if c.url_pattern:
            entry["url"] = c.url_pattern
        results.append(entry)
    return json.dumps({"success": True, "result": results})


@registry.register(
    name="create_search",
    description="Create a new saved search to monitor for housing listings.",
    parameters={
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["craigslist", "facebook"], "description": "Platform to search"},
            "city": {"type": "string", "description": "City for Craigslist searches (e.g. sf, nyc, la)"},
            "section": {"type": "string", "enum": ["rooms", "apartments", "sublets", "housing"], "description": "Craigslist section"},
            "url": {"type": "string", "description": "Facebook group URL"},
        },
        "required": ["platform"],
    },
)
async def create_search(context: ToolContext, platform: str, city: str = None, section: str = None, url: str = None) -> str:
    config = SearchConfig(
        platform=platform,
        query=section,
        city=city,
        url_pattern=url,
        room_id=context.room_id,
    )
    config_id = await db.add_search_config(config)
    return json.dumps({"success": True, "result": f"Search #{config_id} created."})


@registry.register(
    name="stop_search",
    description="Deactivate a saved search by its ID.",
    parameters={
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "Search config ID to deactivate"},
        },
        "required": ["id"],
    },
)
async def stop_search(context: ToolContext, id: int) -> str:
    await db.deactivate_search(id)
    return json.dumps({"success": True, "result": f"Search #{id} deactivated."})


@registry.register(
    name="save_note",
    description="Save a note or preference to persistent storage. Useful for remembering user preferences, bookmarked listings, etc.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Note key/category (e.g. 'preferences', 'bookmarks')"},
            "content": {"type": "string", "description": "Note content"},
        },
        "required": ["key", "content"],
    },
)
async def save_note(context: ToolContext, key: str, content: str) -> str:
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS notes
               (key TEXT PRIMARY KEY, content TEXT, room_id TEXT, updated_at TEXT)"""
        )
        await conn.execute(
            "INSERT OR REPLACE INTO notes (key, content, room_id, updated_at) VALUES (?, ?, ?, datetime('now'))",
            (key, content, context.room_id),
        )
        await conn.commit()
    return json.dumps({"success": True, "result": f"Note '{key}' saved."})


@registry.register(
    name="get_notes",
    description="Retrieve saved notes or preferences.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Note key to retrieve. Omit to get all notes."},
        },
        "required": [],
    },
)
async def get_notes(context: ToolContext, key: str = None) -> str:
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS notes
               (key TEXT PRIMARY KEY, content TEXT, room_id TEXT, updated_at TEXT)"""
        )
        if key:
            async with conn.execute("SELECT content FROM notes WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
            if row:
                return json.dumps({"success": True, "result": row[0]})
            return json.dumps({"success": True, "result": f"No note found for key '{key}'."})
        else:
            async with conn.execute("SELECT key, content FROM notes") as cur:
                rows = await cur.fetchall()
            if not rows:
                return json.dumps({"success": True, "result": "No notes saved."})
            return json.dumps({"success": True, "result": {r[0]: r[1] for r in rows}})
