from __future__ import annotations
import json

from app import db
from app.models import Listing, SearchConfig
from app.tools import registry, ToolContext


@registry.register(
    name="search_craigslist",
    description="Search Craigslist for housing listings. Crawls the site and returns results.",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City to search. Supported: sf, nyc, la, seattle, portland, chicago, denver, austin, boston, dc, philly, miami, atlanta, sd",
            },
            "section": {
                "type": "string",
                "enum": ["rooms", "apartments", "sublets", "housing"],
                "description": "Type of housing to search for",
            },
            "query": {
                "type": "string",
                "description": "Optional search query to filter results",
            },
        },
        "required": ["city", "section"],
    },
)
async def search_craigslist(context: ToolContext, city: str, section: str, query: str = None) -> str:
    config = SearchConfig(
        platform="craigslist",
        query=section if not query else query,
        city=city,
        room_id=context.room_id,
    )

    if not context.cl_crawler:
        return json.dumps({"success": False, "error": "no_crawler", "reason": "Craigslist crawler not available"})

    listings = await context.cl_crawler.crawl(config)

    # Save to DB and dedup
    new_count = 0
    for listing in listings:
        is_new = await db.insert_listing(listing)
        if is_new:
            new_count += 1

    # Format results
    results = []
    for l in listings[:15]:
        entry = {"title": l.title, "url": l.url}
        if l.price:
            entry["price"] = l.price
        if l.location:
            entry["location"] = l.location
        results.append(entry)

    return json.dumps({
        "success": True,
        "result": {
            "total_found": len(listings),
            "new_listings": new_count,
            "listings": results,
        },
    })


@registry.register(
    name="search_facebook_group",
    description="Crawl a Facebook group for housing-related posts. Requires Facebook cookies to be set up.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Facebook group URL to crawl"},
        },
        "required": ["url"],
    },
)
async def search_facebook_group(context: ToolContext, url: str) -> str:
    if not context.browser:
        return json.dumps({"success": False, "error": "no_browser", "reason": "Browser not available"})

    from app.crawlers.facebook import FacebookCrawler
    crawler = FacebookCrawler(context.browser)
    config = SearchConfig(
        platform="facebook",
        url_pattern=url,
        room_id=context.room_id,
    )

    listings = await crawler.crawl(config)

    new_count = 0
    for listing in listings:
        is_new = await db.insert_listing(listing)
        if is_new:
            new_count += 1

    results = []
    for l in listings[:10]:
        entry = {"title": l.title, "url": l.url}
        if l.price:
            entry["price"] = l.price
        if l.description:
            entry["description"] = l.description[:200]
        results.append(entry)

    return json.dumps({
        "success": True,
        "result": {
            "total_found": len(listings),
            "new_listings": new_count,
            "listings": results,
        },
    })
