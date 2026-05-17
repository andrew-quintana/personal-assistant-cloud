from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path

from app.crawlers.base import BaseCrawler
from app.models import Listing, SearchConfig

log = logging.getLogger(__name__)

COOKIES_PATH = os.environ.get("FB_COOKIES_PATH", "/data/cookies/fb_cookies.json")

# Keywords that suggest a housing post
HOUSING_KEYWORDS = re.compile(
    r"\b(room|rent|lease|sublet|available|move.?in|looking for|"
    r"roommate|shared|apartment|studio|bedroom|br|ba|sqft|deposit|"
    r"utilities|furnished|unfurnished)\b",
    re.IGNORECASE,
)

PRICE_PATTERN = re.compile(r"\$[\d,]+")


class FacebookCrawler(BaseCrawler):
    def __init__(self, browser):
        self.browser = browser

    async def crawl(self, config: SearchConfig) -> list[Listing]:
        group_url = config.url_pattern
        if not group_url:
            log.error("No Facebook group URL provided")
            return []

        cookies_path = Path(COOKIES_PATH)
        if not cookies_path.exists():
            log.error(
                f"Facebook cookies not found at {COOKIES_PATH}. "
                "Log in manually and export cookies first."
            )
            return []

        context = await self.browser.new_context(
            storage_state=str(cookies_path),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        try:
            page = await context.new_page()
            log.info(f"Navigating to {group_url}")
            await page.goto(group_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for content to load
            await page.wait_for_timeout(3000)

            # Scroll a few times to load more posts
            for i in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(random.randint(2000, 4000))

            # Extract post content
            posts = await self._extract_posts(page, group_url)
            log.info(f"Extracted {len(posts)} housing-related posts from Facebook group")
            return posts

        except Exception as e:
            log.error(f"Facebook crawl failed: {e}")
            return []
        finally:
            await context.close()

    async def _extract_posts(self, page, group_url: str) -> list[Listing]:
        # Facebook's DOM is notoriously unstable. Use broad selectors.
        # Look for post containers with role="article" or data-ad-preview
        post_elements = await page.query_selector_all('[role="article"]')
        listings: list[Listing] = []

        for post_el in post_elements:
            try:
                text = await post_el.inner_text()
                if not text or not HOUSING_KEYWORDS.search(text):
                    continue

                # Try to extract a permalink
                permalink = None
                link_els = await post_el.query_selector_all("a[href]")
                for link_el in link_els:
                    href = await link_el.get_attribute("href")
                    if href and "/posts/" in href or "/permalink/" in href:
                        permalink = href
                        break

                if not permalink:
                    permalink = group_url

                # Extract price if present
                price = None
                price_match = PRICE_PATTERN.search(text)
                if price_match:
                    try:
                        price = int(price_match.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass

                # Use first line as title, rest as description
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                title = lines[0][:120] if lines else "Facebook post"
                description = "\n".join(lines[:10])

                # Extract images
                image_urls = []
                img_els = await post_el.query_selector_all("img[src]")
                for img_el in img_els:
                    src = await img_el.get_attribute("src")
                    if src and "scontent" in src:
                        image_urls.append(src)

                listings.append(
                    Listing(
                        source="facebook",
                        title=title,
                        price=price,
                        url=permalink,
                        description=description,
                        image_urls=image_urls[:3],
                        crawled_at=datetime.utcnow(),
                    )
                )
            except Exception as e:
                log.debug(f"Failed to parse Facebook post: {e}")
                continue

        return listings
