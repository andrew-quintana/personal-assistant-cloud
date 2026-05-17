"""Agent-facing scheduler tools.

The user (and the bot) declare scheduled jobs in
`/obsidian/_dashboards/scheduled-jobs.md`. The agent uses these tools to
report status and propose new schedule entries.

Use these when the user asks:
- "what jobs are scheduled?" / "is my apartment search running?"
- "when did the last apartment update run?"
- "can you set up a daily X?" — propose, then the user confirms

Full protocol in `docs/SCHEDULER.md`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import aiosqlite

from app import db
from app.jobs import scheduler_loader
from app.tools import registry, ToolContext, YELLOW

log = logging.getLogger(__name__)


@registry.register(
    name="scheduled_jobs_status",
    description=(
        "Report the current scheduled jobs + their most recent run history. "
        "Use this when the user asks anything about cron/schedule, whether a "
        "recurring task is running, when the last run happened, or why "
        "expected updates didn't arrive."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)
async def scheduled_jobs_status(context: ToolContext) -> str:
    rows = scheduler_loader._ensure_md_exists()
    recent = []
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT title, status, started_at, duration_ms, error "
            "FROM scheduled_runs ORDER BY started_at DESC LIMIT 30"
        ) as cur:
            for r in await cur.fetchall():
                recent.append({k: r[k] for k in r.keys()})
    return json.dumps({
        "success": True,
        "result": {
            "jobs_declared": [
                {"title": r.title, "cron": r.cron, "action": r.action,
                 "last_run": r.last_run, "status": r.status}
                for r in rows
            ],
            "recent_runs": recent,
        },
    })


@registry.register(
    name="list_schedulable_actions",
    description=(
        "List the action IDs that can be used in scheduled-jobs.md. Use this "
        "before proposing a new scheduled job so you don't reference an action "
        "that doesn't exist."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)
async def list_schedulable_actions(context: ToolContext) -> str:
    return json.dumps({
        "success": True,
        "result": sorted(scheduler_loader.ACTIONS),
    })


@registry.register(
    name="propose_scheduled_job",
    description=(
        "Append a new job row to scheduled-jobs.md. Use ONLY after the user "
        "explicitly confirms they want this job. The new job takes effect on "
        "the next /jobs/scheduler/reload (or crawler restart)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Kebab-case unique title, e.g. 'craigslist-sf-daily'.",
            },
            "cron": {
                "type": "string",
                "description": "Standard 5-field cron expression in UTC, e.g. '0 8 * * *'.",
            },
            "action": {
                "type": "string",
                "description": (
                    "Action ID from list_schedulable_actions. Must already exist "
                    "in app/jobs/scheduler_loader.py:ACTIONS."
                ),
            },
        },
        "required": ["title", "cron", "action"],
    },
    safety=YELLOW,
    admin_only=True,
)
async def propose_scheduled_job(context: ToolContext, title: str, cron: str, action: str) -> str:
    if action not in scheduler_loader.ACTIONS:
        return json.dumps({
            "success": False,
            "error": "unknown_action",
            "reason": f"Action '{action}' is not registered. "
                      f"Available: {sorted(scheduler_loader.ACTIONS)}",
        })
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger.from_crontab(cron, timezone="UTC")
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": "bad_cron",
            "reason": f"'{cron}' is not a valid 5-field cron expression: {e}",
        })

    rows = scheduler_loader._ensure_md_exists()
    if any(r.title == title for r in rows):
        return json.dumps({
            "success": False,
            "error": "duplicate_title",
            "reason": f"A job titled '{title}' already exists. Pick another title or remove the old row first.",
        })

    rows.append(scheduler_loader.JobRow(title=title, cron=cron, action=action))
    scheduler_loader.JOBS_MD.write_text(scheduler_loader._render(rows))
    return json.dumps({
        "success": True,
        "result": (
            f"Added job '{title}' running `{cron}` UTC → `{action}`. "
            "Call /jobs/scheduler/reload to activate without a restart, or "
            "wait for the next crawler restart."
        ),
    })
