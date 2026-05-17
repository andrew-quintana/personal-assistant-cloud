from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app import db
from app.crawlers.craigslist import CraigslistCrawler
from app.jobs.apartment_search import run_daily_update as run_apartment_update
from app.jobs.cookie_watch import run as run_cookie_watch
from app.jobs.scheduler_loader import (
    SchedulerContext,
    load_and_schedule,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Globals managed by lifespan
bot = None
browser = None
scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, browser

    # Init database
    await db.init_db()
    log.info("Database initialized")

    # Start Playwright
    from playwright.async_api import async_playwright
    pw_instance = await async_playwright().start()
    browser = await pw_instance.chromium.launch(headless=True)
    log.info("Playwright browser started")

    # Crawlers
    cl_crawler = CraigslistCrawler()

    # Import all tools to trigger registration
    import app.tools.data
    import app.tools.crawlers
    import app.tools.browser
    import app.tools.files
    import app.tools.rooms
    import app.tools.cookies
    import app.tools.web_search
    import app.tools.schedules
    from app.tools import registry

    log.info(f"Registered {len(registry._tools)} tools")

    # Create agent
    from app.agent import AgentLoop
    agent = AgentLoop(
        tool_registry=registry,
        browser=browser,
        cl_crawler=cl_crawler,
    )

    # Create bot with agent
    from app.matrix_bot import HermesBot
    bot = HermesBot(agent=agent)
    bot_task = asyncio.create_task(bot.start())

    # Give agent access to matrix client after bot login
    await asyncio.sleep(3)
    agent.matrix_client = bot.client

    # Scheduler — jobs declared in /obsidian/_dashboards/scheduled-jobs.md
    global scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    sched_ctx = SchedulerContext(browser=browser, matrix_client=bot.client)
    scheduled = load_and_schedule(scheduler, sched_ctx)
    scheduler.start()
    log.info(
        "Scheduler started — %d job(s) loaded from scheduled-jobs.md: %s",
        len(scheduled),
        ", ".join(r.title for r in scheduled) or "(none)",
    )

    yield

    # Shutdown
    log.info("Shutting down...")
    if scheduler:
        scheduler.shutdown(wait=False)
    await bot.stop()
    bot_task.cancel()
    await cl_crawler.close()
    await browser.close()
    await pw_instance.stop()


app = FastAPI(title="Hermes Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "bot_running": bot._running if bot else False}


@app.post("/jobs/apartment-search/run")
async def trigger_apartment_search():
    """Manually trigger the daily apartment-search update.

    Useful for local testing without waiting for the cron tick.
    """
    matrix_client = bot.client if bot else None
    result = await run_apartment_update(matrix_client=matrix_client)
    return {"status": "ok", "result": result}


@app.post("/jobs/cookie-watch/run")
async def trigger_cookie_watch():
    """Manually run the cookie health check + Matrix notification."""
    matrix_client = bot.client if bot else None
    result = await run_cookie_watch(browser=browser, matrix_client=matrix_client)
    return {"status": "ok", "result": result}


@app.post("/jobs/scheduler/reload")
async def reload_scheduler():
    """Re-read scheduled-jobs.md and update the APScheduler entries.

    Useful after the bot or user edits the markdown — no full restart needed.
    """
    if not scheduler:
        return {"status": "error", "reason": "scheduler not initialised"}
    ctx = SchedulerContext(
        browser=browser,
        matrix_client=bot.client if bot else None,
    )
    rows = load_and_schedule(scheduler, ctx)
    return {
        "status": "ok",
        "scheduled": [{"title": r.title, "cron": r.cron, "action": r.action} for r in rows],
    }


@app.get("/jobs/scheduler/status")
async def scheduler_status():
    """Snapshot of current jobs + their most recent run from the DB."""
    import aiosqlite
    if not scheduler:
        return {"status": "error", "reason": "scheduler not initialised"}
    jobs = [
        {"id": j.id, "next_run_time": str(j.next_run_time)}
        for j in scheduler.get_jobs()
        if j.id.startswith("scheduled:")
    ]
    recent = []
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT title, action, started_at, finished_at, status, duration_ms "
            "FROM scheduled_runs ORDER BY started_at DESC LIMIT 20"
        ) as cur:
            for r in await cur.fetchall():
                recent.append({k: r[k] for k in r.keys()})
    return {"status": "ok", "jobs": jobs, "recent_runs": recent}


@app.get("/rooms")
async def list_rooms():
    """List Matrix rooms the bot has joined. Useful for finding the room ID
    to set in APARTMENT_UPDATE_ROOM."""
    if not bot or not bot.client:
        return {"status": "error", "reason": "bot not ready"}
    rooms = []
    for rid, r in bot.client.rooms.items():
        rooms.append({
            "room_id": rid,
            "name": r.display_name or "",
            "members": r.member_count,
        })
    return {"status": "ok", "rooms": rooms}
