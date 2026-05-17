"""Reusable agent-side rendering "skills".

These are deterministic Python helpers (not LLM-driven) that produce the
human-facing HTML artifacts the agent writes into the user's Obsidian vault:

- `dashboard` builds persistent, in-place-updated HTML dashboards
- `report` builds one-off, dated HTML reports inside a PARA folder

Jobs (like `app.jobs.apartment_search`) compose these to produce their output.
"""
