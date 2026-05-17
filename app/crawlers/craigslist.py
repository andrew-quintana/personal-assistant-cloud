from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from app.crawlers.base import BaseCrawler
from app.models import Listing, SearchConfig

log = logging.getLogger(__name__)

CITY_MAP = {
    "sf": "sfbay",
    "bay": "sfbay",
    "nyc": "newyork",
    "la": "losangeles",
    "seattle": "seattle",
    "portland": "portland",
    "chicago": "chicago",
    "denver": "denver",
    "austin": "austin",
    "boston": "boston",
    "dc": "washingtondc",
    "philly": "philadelphia",
    "miami": "miami",
    "atlanta": "atlanta",
    "san diego": "sandiego",
    "sd": "sandiego",
}

SECTION_MAP = {
    "rooms": "roo",
    "room": "roo",
    "apartments": "apa",
    "apartment": "apa",
    "sublets": "sub",
    "sublet": "sub",
    "housing": "hou",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class CraigslistCrawler(BaseCrawler):
    def __init__(self):
        self.client = httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30)

    async def crawl(self, config: SearchConfig) -> list[Listing]:
        city = CITY_MAP.get((config.city or "").lower(), config.city or "sfbay")
        section = SECTION_MAP.get((config.query or "rooms").lower(), "roo")
        url = f"https://{city}.craigslist.org/search/{section}"

        params = {}
        if config.query and config.query.lower() not in SECTION_MAP:
            params["query"] = config.query

        log.info(f"Crawling {url} params={params}")

        try:
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            log.error(f"Craigslist request failed: {e}")
            return []

        return self._parse_results(resp.text, city)

    def _parse_results(self, html: str, city: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[Listing] = []

        # Craigslist search results use .cl-search-result or .result-row
        results = soup.select("li.cl-search-result, .result-row")
        if not results:
            # Fallback: try gallery items
            results = soup.select(".cl-static-search-result")

        for item in results:
            try:
                listing = self._parse_item(item, city)
                if listing:
                    listings.append(listing)
            except Exception as e:
                log.debug(f"Failed to parse listing: {e}")
                continue

        log.info(f"Parsed {len(listings)} listings from Craigslist")
        return listings

    def _parse_item(self, item, city: str) -> Listing | None:
        # Try to find the link
        link_el = item.select_one("a.titlestring, a.posting-title, a.result-title, a[href]")
        if not link_el:
            return None

        title = link_el.get_text(strip=True)
        href = link_el.get("href", "")
        if not href:
            return None
        if href.startswith("/"):
            href = f"https://{city}.craigslist.org{href}"

        # Price
        price = None
        price_el = item.select_one(".priceinfo, .result-price, .price")
        if price_el:
            price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "")
            try:
                price = int(price_text)
            except ValueError:
                pass

        # Location
        location = None
        loc_el = item.select_one(".meta .location, .result-hood, .nearby")
        if loc_el:
            location = loc_el.get_text(strip=True).strip("()")

        return Listing(
            source="craigslist",
            title=title,
            price=price,
            location=location,
            url=href,
            crawled_at=datetime.utcnow(),
        )

    async def close(self):
        await self.client.aclose()
