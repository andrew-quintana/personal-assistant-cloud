from __future__ import annotations
import json
import logging
import os
import time
from urllib.parse import quote_plus

from app.tools import registry, ToolContext, validate_url, is_red_zone_element, YELLOW

log = logging.getLogger(__name__)

COOKIES_DIR = "/data/cookies"

# Map domains to cookie files
COOKIE_FILES = {
    "facebook.com": "fb_cookies.json",
    "messenger.com": "fb_cookies.json",
    "google.com": "gmail_cookies.json",
    "mail.google.com": "gmail_cookies.json",
}


def _get_cookie_file(url: str) -> str | None:
    """Find matching cookie file for a URL domain."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
        for domain, filename in COOKIE_FILES.items():
            if host.endswith(domain):
                path = os.path.join(COOKIES_DIR, filename)
                if os.path.exists(path):
                    return path
    except Exception:
        pass
    return None


async def _get_page_content(page) -> str:
    """Get page content as text, with aria snapshot fallback to inner_text."""
    try:
        # Try aria snapshot (Playwright 1.49+)
        content = await page.locator("body").aria_snapshot()
        if content and len(content) > 100:
            if len(content) > 4000:
                content = content[:4000] + "\n... (truncated)"
            return content
    except Exception:
        pass

    # Fallback to inner_text
    try:
        text = await page.inner_text("body")
        return text[:4000]
    except Exception:
        return "(could not read page content)"


async def _ensure_page(context: ToolContext, url: str = None):
    """Get or create a browser page, loading cookies if available for the URL."""
    page = context.browser_page
    if page and not page.is_closed():
        return page

    # Check for cookies matching the URL
    cookie_file = _get_cookie_file(url) if url else None
    kwargs = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    if cookie_file:
        kwargs["storage_state"] = cookie_file
        log.info(f"Loading cookies from {cookie_file}")

    ctx = await context.browser.new_context(**kwargs)
    page = await ctx.new_page()
    context.browser_page = page
    return page


@registry.register(
    name="browse_url",
    description="Navigate to a URL and return the page content. Automatically loads saved cookies for Facebook, Gmail, etc.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"},
        },
        "required": ["url"],
    },
)
async def browse_url(context: ToolContext, url: str) -> str:
    err = validate_url(url)
    if err:
        return json.dumps({"success": False, "error": "blocked_url", "reason": err})

    page = await _ensure_page(context, url)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        content = await _get_page_content(page)

        return json.dumps({
            "success": True,
            "result": {
                "title": await page.title(),
                "url": page.url,
                "content": content,
            },
        })
    except Exception as e:
        return json.dumps({"success": False, "error": "navigation_error", "reason": str(e), "retry": True})


@registry.register(
    name="search_web",
    description="Search the web. Returns top results with titles, URLs, and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
)
async def search_web(context: ToolContext, query: str) -> str:
    """Use Playwright to search Google (handles JS-rendered results)."""
    page = await _ensure_page(context)

    try:
        search_url = f"https://www.google.com/search?q={quote_plus(query)}&num=10"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # Extract results using JS to handle Google's dynamic DOM
        results = await page.evaluate("""() => {
            const results = [];
            // Try multiple selector patterns Google uses
            const items = document.querySelectorAll('div.g, div[data-hveid] > div > div > a[href^="http"]');
            for (const item of items) {
                const a = item.tagName === 'A' ? item : item.querySelector('a[href^="http"]');
                const h3 = item.querySelector('h3');
                if (a && h3) {
                    const href = a.href;
                    if (href && !href.includes('google.com') && !href.includes('accounts.google')) {
                        // Get snippet from nearby text
                        const parent = h3.closest('div.g') || h3.parentElement?.parentElement?.parentElement;
                        const allText = parent ? parent.innerText : '';
                        const titleText = h3.innerText;
                        const snippet = allText.replace(titleText, '').trim().substring(0, 200);
                        results.push({
                            title: titleText,
                            url: href,
                            snippet: snippet
                        });
                    }
                }
                if (results.length >= 10) break;
            }
            return results;
        }""")

        if not results:
            # Fallback: just return the page text
            text = await page.inner_text("body")
            return json.dumps({"success": True, "result": {"raw_text": text[:3000]}})

        return json.dumps({"success": True, "result": results})
    except Exception as e:
        return json.dumps({"success": False, "error": "search_error", "reason": str(e), "retry": True})


@registry.register(
    name="click",
    description="Click an element on the current page by CSS selector. Safety: will refuse to click send/submit/pay buttons.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of element to click"},
        },
        "required": ["selector"],
    },
    safety=YELLOW,
)
async def click(context: ToolContext, selector: str) -> str:
    page = context.browser_page
    if not page or page.is_closed():
        return json.dumps({"success": False, "error": "no_page", "reason": "No page open. Use browse_url first."})

    try:
        element = await page.query_selector(selector)
        if not element:
            return json.dumps({"success": False, "error": "not_found", "reason": f"Element '{selector}' not found", "retry": True})

        text = ""
        try:
            text = await element.inner_text()
        except Exception:
            pass

        if text and is_red_zone_element(text):
            return json.dumps({
                "success": False,
                "error": "blocked",
                "reason": f"Cannot click this element ('{text[:50]}') — it appears to perform a dangerous action.",
            })

        await element.click()
        await page.wait_for_timeout(1500)

        return json.dumps({"success": True, "result": f"Clicked '{text[:50]}'. Page URL: {page.url}"})
    except Exception as e:
        return json.dumps({"success": False, "error": "click_error", "reason": str(e), "retry": True})


@registry.register(
    name="scroll",
    description="Scroll the current page up or down and return updated content.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction"},
        },
        "required": ["direction"],
    },
)
async def scroll(context: ToolContext, direction: str) -> str:
    page = context.browser_page
    if not page or page.is_closed():
        return json.dumps({"success": False, "error": "no_page", "reason": "No page open. Use browse_url first."})

    delta = 800 if direction == "down" else -800
    await page.evaluate(f"window.scrollBy(0, {delta})")
    await page.wait_for_timeout(1000)

    content = await _get_page_content(page)
    return json.dumps({"success": True, "result": {"scrolled": direction, "content": content[:3000]}})


@registry.register(
    name="fill",
    description="Fill a form field on the current page. For creating drafts, NOT for submitting forms.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of the input field"},
            "text": {"type": "string", "description": "Text to fill in"},
        },
        "required": ["selector", "text"],
    },
)
async def fill(context: ToolContext, selector: str, text: str) -> str:
    page = context.browser_page
    if not page or page.is_closed():
        return json.dumps({"success": False, "error": "no_page", "reason": "No page open. Use browse_url first."})

    try:
        await page.fill(selector, text)
        return json.dumps({"success": True, "result": f"Filled field '{selector}' with text."})
    except Exception as e:
        return json.dumps({"success": False, "error": "fill_error", "reason": str(e), "retry": True})


@registry.register(
    name="screenshot",
    description="Take a screenshot of the current page. Returns the file path.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def screenshot(context: ToolContext) -> str:
    page = context.browser_page
    if not page or page.is_closed():
        return json.dumps({"success": False, "error": "no_page", "reason": "No page open. Use browse_url first."})

    path = f"/tmp/screenshot_{int(time.time())}.png"
    await page.screenshot(path=path)
    return json.dumps({"success": True, "result": f"Screenshot saved to {path}"})


@registry.register(
    name="get_page_text",
    description="Get the full text content of the current page. Use when you need more detail than browse_url provides.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def get_page_text(context: ToolContext) -> str:
    page = context.browser_page
    if not page or page.is_closed():
        return json.dumps({"success": False, "error": "no_page", "reason": "No page open. Use browse_url first."})

    text = await page.inner_text("body")
    return json.dumps({"success": True, "result": {"url": page.url, "text": text[:6000]}})
