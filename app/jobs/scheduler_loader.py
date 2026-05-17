"""Declarative scheduler loader.

Source of truth: `/obsidian/_dashboards/scheduled-jobs.md`. The user (and the
bot) can edit that file to add/remove/retune scheduled jobs. On crawler
startup this module:

1. Parses the markdown table of jobs.
2. For each row, looks up the action by string ID in `ACTIONS` and schedules
   it via APScheduler with a cron expression from the row.
3. Wraps each invocation with a DB writer that logs to `scheduled_runs` and
   rewrites the row's Last run / Status cells in the markdown.

If the markdown file is missing or empty, falls back to a default schedule so
the system stays useful out of the box.

Add a new job:
- Implement the function in the codebase.
- Register a string ID → coroutine wrapper in `ACTIONS` below.
- Add a row to `scheduled-jobs.md` with that action ID.
- Restart the crawler (or call `/jobs/scheduler/reload`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db
from app.jobs.apartment_search import run_daily_update as _apartment_update
from app.jobs.cookie_watch import run as _cookie_watch

log = logging.getLogger(__name__)

JOBS_MD = Path("/obsidian/_dashboards/scheduled-jobs.md")


# ---------------------------------------------------------------------------
# Action registry — string ID → coroutine that returns a result dict.
#
# Each action receives a SchedulerContext with browser + matrix_client and
# returns a small dict that's serialised into output_summary.
# ---------------------------------------------------------------------------
@dataclass
class SchedulerContext:
    browser: Any = None
    matrix_client: Any = None


ACTIONS: dict[str, Callable[[SchedulerContext], Awaitable[dict]]] = {
    "apartment_search.run_daily_update": lambda ctx: _apartment_update(
        matrix_client=ctx.matrix_client,
    ),
    "cookie_watch.run": lambda ctx: _cookie_watch(
        browser=ctx.browser,
        matrix_client=ctx.matrix_client,
    ),
}


# ---------------------------------------------------------------------------
# Default schedule used when the markdown file is missing or empty.
# ---------------------------------------------------------------------------
DEFAULT_JOBS: list[dict] = [
    {"title": "apartment-daily-update", "cron": "0 8 * * *",     "action": "apartment_search.run_daily_update"},
    {"title": "cookie-watch",            "cron": "15 0,12 * * *", "action": "cookie_watch.run"},
]


DEFAULT_MD_HEADER = """---
title: Scheduled Jobs
type: dashboard
audience: agent + user
---

# Scheduled Jobs

Source of truth for what `hermes-crawler` runs on a schedule. **Edit the
table below** to add, change, or remove jobs. Changes take effect at the
next crawler restart (or `curl -X POST http://localhost:8000/jobs/scheduler/reload`).

- **Title** — short kebab-case name; used as job identity and DB key.
- **Schedule** — standard 5-field cron, **UTC**.
- **Action** — string ID registered in `app/jobs/scheduler_loader.py:ACTIONS`.
- **Last run** / **Status** — auto-updated after each run; do not edit by hand.

## Jobs

"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
@dataclass
class JobRow:
    title: str
    cron: str
    action: str
    last_run: str = "—"
    status: str = "pending"


_ROW_RE = re.compile(
    r"^\|\s*(?P<title>[a-z0-9][\w\-]*)\s*"
    r"\|\s*(?P<cron>[^|]+?)\s*"
    r"\|\s*(?P<action>[a-zA-Z_][\w\.]*)\s*"
    r"\|\s*(?P<last>[^|]*?)\s*"
    r"\|\s*(?P<status>[^|]*?)\s*\|\s*$"
)


def _parse(md_text: str) -> list[JobRow]:
    rows: list[JobRow] = []
    for line in md_text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        if m.group("title") in {"title", "Title"}:
            continue  # header / separator
        rows.append(JobRow(
            title=m.group("title"),
            cron=m.group("cron"),
            action=m.group("action"),
            last_run=m.group("last") or "—",
            status=m.group("status") or "pending",
        ))
    return rows


def _render(rows: list[JobRow]) -> str:
    body = ["| Title | Schedule (UTC) | Action | Last run | Status |",
            "|-------|---------------|--------|----------|--------|"]
    for r in rows:
        body.append(f"| {r.title} | `{r.cron}` | `{r.action}` | {r.last_run} | {r.status} |")
    avail = (
        "\n## Available actions\n\n"
        + "\n".join(f"- `{a}`" for a in sorted(ACTIONS)) + "\n"
    )
    return DEFAULT_MD_HEADER + "\n".join(body) + "\n" + avail


def _ensure_md_exists() -> list[JobRow]:
    """Read the md if present; otherwise seed defaults and write."""
    if JOBS_MD.exists():
        rows = _parse(JOBS_MD.read_text())
        if rows:
            return rows
    JOBS_MD.parent.mkdir(parents=True, exist_ok=True)
    rows = [JobRow(**j) for j in DEFAULT_JOBS]
    JOBS_MD.write_text(_render(rows))
    log.info("scheduler_loader: seeded %s with %d default jobs", JOBS_MD, len(rows))
    return rows


def _update_status(title: str, last_run: str, status: str) -> None:
    """Rewrite the matching row's last_run/status cells in place."""
    if not JOBS_MD.exists():
        return
    rows = _parse(JOBS_MD.read_text())
    changed = False
    for r in rows:
        if r.title == title:
            r.last_run = last_run
            r.status = status
            changed = True
            break
    if changed:
        JOBS_MD.write_text(_render(rows))


# ---------------------------------------------------------------------------
# DB logging
# ---------------------------------------------------------------------------
async def _log_start(title: str, action: str, started_at: str) -> int:
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO scheduled_runs (title, action, started_at, status) "
            "VALUES (?, ?, ?, 'running')",
            (title, action, started_at),
        )
        await conn.commit()
        return cur.lastrowid


async def _log_finish(run_id: int, status: str, duration_ms: int,
                      output_summary: str = "", error: str = "") -> None:
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "UPDATE scheduled_runs SET finished_at=?, status=?, duration_ms=?, "
            "output_summary=?, error=? WHERE id=?",
            (finished_at, status, duration_ms,
             output_summary[:2000], error[:1000], run_id),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Wrapper: invoked by APScheduler for each job tick
# ---------------------------------------------------------------------------
def _make_runner(row: JobRow, ctx: SchedulerContext) -> Callable[[], Awaitable[None]]:
    async def _run():
        action_fn = ACTIONS.get(row.action)
        if action_fn is None:
            log.error("scheduled job %s references unknown action %s", row.title, row.action)
            return
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.monotonic()
        run_id = await _log_start(row.title, row.action, started_at)
        try:
            result = await action_fn(ctx)
            elapsed = int((time.monotonic() - t0) * 1000)
            summary = json.dumps(result)[:2000] if isinstance(result, dict) else str(result)[:2000]
            await _log_finish(run_id, "success", elapsed, output_summary=summary)
            _update_status(row.title, started_at, "success")
            log.info("scheduled job %s ok in %dms", row.title, elapsed)
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            await _log_finish(run_id, "failed", elapsed, error=str(e))
            _update_status(row.title, started_at, "failed")
            log.error("scheduled job %s FAILED in %dms: %s", row.title, elapsed, e, exc_info=True)
    return _run


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def load_and_schedule(scheduler: AsyncIOScheduler, ctx: SchedulerContext) -> list[JobRow]:
    """Read scheduled-jobs.md and add each job to the APScheduler instance.

    Removes any previously-scheduled jobs from the loader (idempotent reload).
    Returns the list of rows that were scheduled.
    """
    # Clear any old jobs we own (prefix-namespaced)
    for j in scheduler.get_jobs():
        if j.id.startswith("scheduled:"):
            scheduler.remove_job(j.id)

    rows = _ensure_md_exists()
    scheduled: list[JobRow] = []
    for r in rows:
        if r.action not in ACTIONS:
            log.warning("skipping %s: unknown action %r", r.title, r.action)
            continue
        try:
            trigger = CronTrigger.from_crontab(r.cron, timezone="UTC")
        except Exception as e:
            log.warning("skipping %s: bad cron %r (%s)", r.title, r.cron, e)
            continue
        scheduler.add_job(
            _make_runner(r, ctx),
            trigger=trigger,
            id=f"scheduled:{r.title}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduled.append(r)
        log.info("scheduled %s @ %s → %s", r.title, r.cron, r.action)
    return scheduled
