# Scheduler skill

The agent runs recurring tasks (apartment search, cookie health check, future
crawlers) via APScheduler. Schedules are declared in **markdown** so the user
and the bot can edit them collaboratively.

## Source of truth

`/obsidian/_dashboards/scheduled-jobs.md` is the canonical job list.

```markdown
| Title | Schedule (UTC) | Action | Last run | Status |
|-------|---------------|--------|----------|--------|
| apartment-daily-update | `0 8 * * *`     | `apartment_search.run_daily_update` | … | … |
| cookie-watch           | `15 0,12 * * *` | `cookie_watch.run`                  | … | … |
```

- **Title**: kebab-case, unique, used as the job's DB key and APScheduler id.
- **Schedule**: standard 5-field cron, **UTC**.
- **Action**: a string ID registered in `app/jobs/scheduler_loader.py:ACTIONS`.
- **Last run** / **Status**: auto-updated after each tick. **Do not edit by hand.**

If the file doesn't exist on startup, the scheduler seeds it with the
defaults (apartment + cookie) and continues.

## Lifecycle

```
crawler starts
    └─→ load_and_schedule() reads scheduled-jobs.md
            └─→ for each row → CronTrigger.from_crontab → APScheduler.add_job
                    └─→ each tick → wrapper:
                            1. INSERT INTO scheduled_runs (status='running')
                            2. await ACTION(ctx)
                            3. UPDATE scheduled_runs (status='success'|'failed', duration, output|error)
                            4. rewrite the row's Last run / Status cells in the md
```

## Run history

Every invocation is logged to `/data/hermes.db` → `scheduled_runs` table:

| column | what |
|---|---|
| id | autoincrement |
| title | matches the md row title |
| action | action ID at the time of run |
| started_at | ISO timestamp, UTC |
| finished_at | ISO timestamp, UTC |
| status | `running` \| `success` \| `failed` |
| duration_ms | elapsed |
| error | short error message on failure |
| output_summary | up to 2 KB of the action's return value |

The md only shows the most recent run; the DB has the full history.

## HTTP endpoints

| Endpoint | What |
|---|---|
| `GET /jobs/scheduler/status` | Live APScheduler jobs + last 20 runs from DB |
| `POST /jobs/scheduler/reload` | Re-read the md and update APScheduler (no restart) |
| `POST /jobs/apartment-search/run` | Manual run of the apartment-search action |
| `POST /jobs/cookie-watch/run` | Manual run of the cookie watch |

## Agent tools

The bot has three scheduler tools:

| Tool | Use it when |
|---|---|
| `scheduled_jobs_status` | User asks anything about cron/schedule/recurring tasks. |
| `list_schedulable_actions` | Before proposing a new job — to confirm the action ID exists. |
| `propose_scheduled_job(title, cron, action)` | After the user explicitly confirms they want a new recurring job. Writes to the md; takes effect on next reload/restart. |

The bot should not invent action IDs. New actions must be added in code
first.

## Adding a new action (code path)

1. Implement the function as a coroutine, e.g. `app/jobs/my_thing.py:run(ctx)`.
2. Register it in `app/jobs/scheduler_loader.py:ACTIONS` with a stable string ID.
3. Add a row to `scheduled-jobs.md` (or have the bot do it via `propose_scheduled_job`).
4. `curl -X POST http://localhost:8000/jobs/scheduler/reload`.

## What this replaces

An earlier exploration created `qDome/Projects/SF Apartment Search/cron/`
with a bash wrapper + a separate SQLite DB. That approach was **not wired
to anything that actually ran** (it shelled out to a `hermes-cli` binary
that didn't exist; the user had to install host cron entries that nothing
in the system could install). Replaced by this in-process design.
