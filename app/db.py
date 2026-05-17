from __future__ import annotations
import json
import os
from datetime import datetime

import aiosqlite

from app.models import Listing, SearchConfig

DB_PATH = os.environ.get("DB_PATH", "/data/hermes.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER,
    location TEXT,
    url TEXT NOT NULL UNIQUE,
    description TEXT,
    image_urls TEXT,
    posted_at TEXT,
    crawled_at TEXT NOT NULL,
    notified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS search_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    query TEXT,
    city TEXT,
    url_pattern TEXT,
    room_id TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def insert_listing(listing: Listing) -> bool:
    """Insert a listing. Returns True if it was new (not a duplicate)."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO listings
                   (id, source, title, price, location, url, description,
                    image_urls, posted_at, crawled_at, notified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    listing.id,
                    listing.source,
                    listing.title,
                    listing.price,
                    listing.location,
                    listing.url,
                    listing.description,
                    json.dumps(listing.image_urls),
                    listing.posted_at.isoformat() if listing.posted_at else None,
                    listing.crawled_at.isoformat(),
                ),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_unsent_listings(source: str | None = None) -> list[Listing]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM listings WHERE notified = 0"
        params: list = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY crawled_at DESC"
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [
            Listing(
                id=r["id"],
                source=r["source"],
                title=r["title"],
                price=r["price"],
                location=r["location"],
                url=r["url"],
                description=r["description"],
                image_urls=json.loads(r["image_urls"]) if r["image_urls"] else [],
                crawled_at=datetime.fromisoformat(r["crawled_at"]),
                notified=bool(r["notified"]),
            )
            for r in rows
        ]


async def mark_notified(listing_ids: list[str]):
    if not listing_ids:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" for _ in listing_ids)
        await db.execute(
            f"UPDATE listings SET notified = 1 WHERE id IN ({placeholders})",
            listing_ids,
        )
        await db.commit()


async def add_search_config(config: SearchConfig) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO search_configs
               (platform, query, city, url_pattern, room_id, active, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (
                config.platform,
                config.query,
                config.city,
                config.url_pattern,
                config.room_id,
                config.created_at.isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def list_search_configs(room_id: str | None = None) -> list[SearchConfig]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM search_configs WHERE active = 1"
        params: list = []
        if room_id:
            query += " AND room_id = ?"
            params.append(room_id)
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [
            SearchConfig(
                id=r["id"],
                platform=r["platform"],
                query=r["query"],
                city=r["city"],
                url_pattern=r["url_pattern"],
                room_id=r["room_id"],
                active=bool(r["active"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]


async def deactivate_search(config_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE search_configs SET active = 0 WHERE id = ?", (config_id,)
        )
        await db.commit()


async def is_url_seen(url: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_urls WHERE url = ?", (url,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_url_seen(url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO seen_urls (url, first_seen) VALUES (?, ?)",
                (url, datetime.utcnow().isoformat()),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            pass
