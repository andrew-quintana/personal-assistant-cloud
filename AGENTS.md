---
title: AGENTS — vault write policy (reference)
audience: any agent (LLM or job code) writing into the user's qDome vault
updated: 2026-05-17
---

# Vault Write Policy (reference copy)

This file mirrors the policy the user maintains inside their Obsidian vault
(`qDome/AGENTS.md`). It is included here so the deployable agent has the same
rules baked into the repo. The vault itself is **not** in this repo.

The vault is mounted at `/obsidian` inside the crawler container (Docker
volume `obsidian-vault`). Anything written there should follow these rules.

## Vault layout (PARA + system)

| Folder | Purpose |
|---|---|
| `00-Inbox/` | Unfiled / raw capture. Drafts only. Promote out within a few days. |
| `Projects/<Project>/` | Bounded efforts with a defined outcome. Reports live here. |
| `Areas/<Area>/` | Ongoing standards/responsibilities. |
| `Resources/<Topic>/` | Reference material organized by topic. |
| `Archive/` | Done/inactive. Never write new content here; move only. |
| `_dashboards/` | Persistent HTML dashboards (live, updated in place). |
| `_databases/` | Structured DB records (tasks, notes, etc.). Follow existing frontmatter. |
| `_templates/`, `_views/`, `_fileClasses/`, `_migration/` | System. Don't write outside existing patterns. |

## File type by audience

| Audience | Format | Where |
|---|---|---|
| **Agent / future-self (source of truth)** | `.md` with frontmatter | PARA folder appropriate to the topic |
| **Human (rich presentation, dashboards)** | `.html` (self-contained, Surfing-renderable) | `_dashboards/<topic>.html` |
| **Human (one-off action-oriented report)** | `.html` | inside the relevant `Projects/<P>/` or `Areas/<A>/` |
| **Spatial overview** | `.canvas` (JSON) | beside the related `.md` |

Rule of thumb: if the content is the *truth*, write `.md`. If the content is
a *view* of the truth, write `.html`.

## Dashboards vs. reports

| | Dashboard | Report |
|---|---|---|
| Lifespan | Persistent | One-off, dated |
| Location | `_dashboards/<topic>.html` | `Projects/<P>/<title>.html` (or Areas/Resources) |
| Update | Overwrite in place | Never overwrite a prior report — write a new one |
| Purpose | Current state, live metrics | Findings to consider, decisions to make |
| Naming | `kebab-case-topic.html` | `YYYY-MM-DD-kebab-title.html` |

In code, these are implemented by `app/skills/dashboard.py` and
`app/skills/report.py`. Jobs (under `app/jobs/`) compose them.

## Naming

- Folders: Title Case (matches existing PARA convention)
- New `.md` files: Title Case matching topic
- HTML artifacts: `kebab-case.html`
- Reports: prefix with ISO date: `2026-05-17-findings.html`

## Frontmatter

Every `.md` you create needs at minimum:

```yaml
---
title: ...
created: YYYY-MM-DDTHH:MM:SS
type: note | task | project | resource | area | report-index
tags: []
---
```

When adding to an existing `_databases/` collection (e.g. tasks), match the
existing frontmatter schema for that folder — don't invent new fields.

## Linking

- Prefer wiki-links: `[[Note Title]]` over relative paths
- HTML artifacts may link back to source `.md` via relative paths so Obsidian Surfing can follow them
- Don't create orphan files — every new note should be reachable from a project, area, or index

## When to update vs. create

- **Update** when the file represents the same logical thing (a dashboard, a project index, a running log).
- **Create** when the content is a new event (a report, a finding, a meeting note).
- If unsure, default to updating — orphan files rot fastest.

## Embedding eligibility

For agents maintaining a vector index of the vault:

| Folder | Index? |
|---|---|
| `Projects/`, `Areas/`, `Resources/` | Yes |
| `00-Inbox/` | No (too noisy / draft) |
| `Archive/` | Optional, lower weight |
| `_databases/`, `_views/`, `_templates/`, `_fileClasses/`, `_migration/` | No |
| `_dashboards/` | No (derived from sources) |
| `assets/` | No |

## Don'ts

- Don't write HTML when an `.md` would do.
- Don't proliferate dashboards — update the existing one for that topic.
- Don't write into `Archive/`.
- Don't create new top-level folders without updating this file.
