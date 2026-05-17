"""Daily SF apartment-search update job.

Filters the listings DB by the user's neighborhood + budget constraints, writes
per-listing markdown notes into the user's Obsidian vault (mounted at
`/obsidian`), refreshes a dashboard HTML, and appends a dated report HTML.
Finally posts a short Matrix summary so the user can drill into the vault from
there.

Triggered by APScheduler in main.py lifespan, or manually via the HTTP endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app import db
from app.skills._style import html_escape
from app.skills.dashboard import Dashboard, KpiCard, Section
from app.skills.report import Report

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (env-driven)
# ---------------------------------------------------------------------------
VAULT_ROOT = Path("/obsidian")
PROJECT_DIR = VAULT_ROOT / "Projects" / "SF Apartment Search"
LISTINGS_DIR = PROJECT_DIR / "listings"
DASHBOARD_PATH = VAULT_ROOT / "_dashboards" / "sf-apartment-search.html"

BUDGET_SOLO = int(os.environ.get("APARTMENT_BUDGET_SOLO", "3000"))
BUDGET_SHARED = int(os.environ.get("APARTMENT_BUDGET_SHARED", "2500"))

TARGET_NEIGHBORHOODS: dict[str, list[str]] = {
    "Pacific Heights": ["pacific heights", "pac heights"],
    "Nob Hill (north of California)": ["nob hill", "upper nob hill"],
    "Russian Hill (south)": ["russian hill"],
}
HARD_EXCLUDES = ["lower nob hill", "tenderloin", "soma", "bayview", "richmond district"]

# Street-level filter. SF cross-street block numbers count up from Market.
# Nob Hill (N of California, S of Pacific) → blocks 1000-1499 on these streets.
# Russian Hill south (S of Lombard, N of Pacific) → 1500-2199.
NS_TARGET_STREETS_NOB_RH = {
    "taylor", "mason", "jones", "leavenworth", "hyde", "larkin", "polk",
}
# Pacific Heights: California ≈ block 2000+. N of California ≈ 2100-2899.
NS_TARGET_STREETS_PAC = {
    "fillmore", "steiner", "pierce", "scott", "divisadero",
    "buchanan", "webster", "laguna", "octavia", "gough",
    "franklin", "van ness",
}
_ADDRESS_RE = re.compile(r"\b(\d{3,4})\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\b", re.IGNORECASE)

SHARED_KEYWORDS = [
    "room for rent", "private room", "roommate", "rooming", "shared apartment",
    "looking for a roommate", "looking for roommate", "room available", "furnished room",
]
SOLO_KEYWORDS = ["studio", "1 bed", "1bed", "1br", "1 br", "junior 1", "1bd", "1 bd"]

USER_ROOM = os.environ.get("APARTMENT_UPDATE_ROOM") or os.environ.get("MATRIX_ADMIN_ROOM", "")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    id: str
    source: str
    title: str
    price: int
    url: str
    description: str
    neighborhood: str
    mode: str
    crawled_at: str
    flags: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", self.title.lower())[:60].strip("-")
        h = hashlib.md5(self.id.encode()).hexdigest()[:6]
        return f"{base}-{h}" if base else h


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def _check_street_address(title: str, description: str) -> str | None:
    """Return reason string if a detected street address is out of zone."""
    blob = f"{title} {description or ''}"
    for m in _ADDRESS_RE.finditer(blob):
        block = int(m.group(1))
        street = m.group(2).lower().strip()
        for suffix in (" street", " st", " avenue", " ave", " blvd", " boulevard"):
            if street.endswith(suffix):
                street = street[: -len(suffix)].strip()
        if street in NS_TARGET_STREETS_NOB_RH:
            if not (1000 <= block <= 2199):
                return f"address-out-of-zone:{block} {street}"
        elif street in NS_TARGET_STREETS_PAC:
            if not (2100 <= block <= 2899):
                return f"address-out-of-zone:{block} {street}"
    return None


def _classify_neighborhood(title: str, description: str) -> str | None:
    blob = f"{title} {description or ''}".lower()
    for excl in HARD_EXCLUDES:
        if excl in blob:
            return None
    if _check_street_address(title, description):
        return None
    for canonical, aliases in TARGET_NEIGHBORHOODS.items():
        for alias in aliases:
            if alias in blob:
                return canonical
    return None


def _classify_mode(title: str, description: str) -> str:
    blob = f"{title} {description or ''}".lower()
    has_shared = any(kw in blob for kw in SHARED_KEYWORDS)
    has_solo = any(kw in blob for kw in SOLO_KEYWORDS)
    if has_shared and not has_solo:
        return "shared"
    if has_solo and not has_shared:
        return "solo"
    if has_shared and has_solo:
        return "both"
    return "unknown"


def _budget_ok(c: Candidate) -> bool:
    if c.mode == "shared":
        return c.price <= BUDGET_SHARED
    if c.mode == "solo":
        return c.price <= BUDGET_SOLO
    if c.mode == "both":
        return c.price <= BUDGET_SOLO
    return c.price <= BUDGET_SOLO


# ---------------------------------------------------------------------------
# Query + filter
# ---------------------------------------------------------------------------
async def _fetch_candidates(limit: int = 500) -> list[Candidate]:
    out: list[Candidate] = []
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM listings WHERE price > 0 ORDER BY crawled_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    for r in rows:
        neighborhood = _classify_neighborhood(r["title"] or "", r["description"] or "")
        if not neighborhood:
            continue
        mode = _classify_mode(r["title"] or "", r["description"] or "")
        c = Candidate(
            id=r["id"],
            source=r["source"],
            title=r["title"] or "(no title)",
            price=int(r["price"] or 0),
            url=r["url"],
            description=r["description"] or "",
            neighborhood=neighborhood,
            mode=mode,
            crawled_at=r["crawled_at"],
        )
        if not _budget_ok(c):
            continue
        if c.mode == "unknown":
            c.flags.append("mode-unknown")
        if c.price > BUDGET_SOLO * 0.95 or c.price > BUDGET_SHARED * 0.95:
            c.flags.append("near-budget-cap")
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Vault writers
# ---------------------------------------------------------------------------
def _ensure_dirs():
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)


def _write_listing_md(c: Candidate, today: str) -> tuple[Path, bool]:
    """Write per-listing markdown. Returns (path, wrote_new)."""
    path = LISTINGS_DIR / f"{today}-{c.slug}.md"
    if path.exists():
        return path, False
    front = {
        "title": c.title,
        "neighborhood": c.neighborhood,
        "mode": c.mode,
        "rent_total": c.price,
        "rent_user_share": c.price,
        "url": c.url,
        "source": c.source,
        "crawled_at": c.crawled_at,
        "status": "new",
        "flags": c.flags,
        "listing_id": c.id,
    }
    fm_lines = ["---"]
    for k, v in front.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: {json.dumps(v)}")
        elif isinstance(v, str):
            fm_lines.append(f'{k}: "{v.replace(chr(34), chr(39))}"')
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    body = [
        "",
        f"# {c.title}",
        "",
        f"- **Neighborhood:** {c.neighborhood}",
        f"- **Mode:** {c.mode}",
        f"- **Price:** ${c.price:,}/mo",
        f"- **Source:** {c.source}",
        f"- **URL:** {c.url}",
        "",
        "## Description",
        "",
        c.description.strip() or "_(no description provided)_",
        "",
    ]
    path.write_text("\n".join(fm_lines + body))
    return path, True


# ---------------------------------------------------------------------------
# HTML rendering (uses skills.dashboard / skills.report)
# ---------------------------------------------------------------------------
def _candidate_row(c: Candidate) -> str:
    flags = "".join(f'<span class="pill warn">{html_escape(f)}</span>' for f in c.flags)
    return (
        f"<tr><td>${c.price:,}</td>"
        f"<td>{html_escape(c.neighborhood)}</td>"
        f'<td><a href="{html_escape(c.url)}" target="_blank">{html_escape(c.title)[:80]}</a></td>'
        f"<td>{html_escape(c.source)}</td>"
        f"<td>{flags}</td></tr>"
    )


def _build_dashboard(candidates: list[Candidate], now: str) -> str:
    solo = [c for c in candidates if c.mode in ("solo", "both", "unknown")]
    shared = [c for c in candidates if c.mode in ("shared", "both")]

    kpis = [
        KpiCard("Total candidates", str(len(candidates))),
        KpiCard(f"Solo (≤ ${BUDGET_SOLO})", str(len(solo))),
        KpiCard(f"Shared (≤ ${BUDGET_SHARED})", str(len(shared))),
    ]
    by_n: dict[str, int] = {}
    for c in candidates:
        by_n[c.neighborhood] = by_n.get(c.neighborhood, 0) + 1
    for k, v in sorted(by_n.items()):
        kpis.append(KpiCard(k, str(v)))

    def _section(name: str, rows: list[Candidate]) -> Section:
        if not rows:
            return Section(f"{name} (0)", "<p><em>No active candidates.</em></p>")
        rows_sorted = sorted(rows, key=lambda x: x.price)
        body = (
            "<table><thead><tr><th>Price</th><th>Neighborhood</th>"
            "<th>Title</th><th>Source</th><th>Flags</th></tr></thead>"
            f"<tbody>{''.join(_candidate_row(c) for c in rows_sorted)}</tbody></table>"
        )
        return Section(f"{name} ({len(rows)})", body)

    return Dashboard(
        title="SF Apartment Search",
        subtitle_html=(
            f"Last updated: {now} · "
            '<a href="../Projects/SF Apartment Search/SF Apartment Search.md">project notes</a>'
        ),
        kpis=kpis,
        sections=[_section("Solo track", solo), _section("Shared track", shared)],
        source="hermes-agent listings DB (target neighborhoods + budget filter)",
    ).render()


def _build_report(candidates: list[Candidate], new_today: list[Candidate], today: str) -> str:
    def _li(c: Candidate) -> str:
        flag_pills = "".join(f'<span class="pill warn">{html_escape(f)}</span>' for f in c.flags)
        return (
            f"<li>${c.price:,} · {html_escape(c.neighborhood)} · "
            f'<a href="{html_escape(c.url)}" target="_blank">{html_escape(c.title)[:90]}</a> '
            f'<span class="pill">{html_escape(c.mode)}</span>{flag_pills}</li>'
        )

    new_section = "".join(_li(c) for c in new_today) or "<li><em>No new listings today.</em></li>"
    top = sorted(candidates, key=lambda x: x.price)[:5]
    top_section = "".join(_li(c) for c in top) or "<li><em>No candidates within constraints.</em></li>"

    tldr = (
        f"{len(new_today)} new listing(s) today, {len(candidates)} total candidates within "
        "constraints (target neighborhoods + budget). Top picks below; per-listing notes in "
        "<code>listings/</code>."
    )
    constraints_html = (
        "<ul>"
        "<li>Neighborhoods: Pacific Heights · Nob Hill (north of California) · Russian Hill (south)</li>"
        f"<li>Solo budget cap: ${BUDGET_SOLO}/mo · Shared budget cap (user's share): ${BUDGET_SHARED}/mo</li>"
        f"<li>Hard excludes: {', '.join(HARD_EXCLUDES)}</li>"
        "</ul>"
    )

    return Report(
        title="SF Apartment Findings",
        iso_date=today,
        project_or_area="SF Apartment Search",
        index_link_html=(
            '<a href="../../_dashboards/sf-apartment-search.html">live dashboard</a> · '
            '<a href="./SF Apartment Search.md">project notes</a>'
        ),
        tldr_html=tldr,
        findings_html=(
            f"<h3>New today</h3><ul>{new_section}</ul>"
            f"<h3>Top candidates (current)</h3><ol>{top_section}</ol>"
        ),
        extra_sections=[("Constraints applied", constraints_html)],
        source="hermes-agent listings DB",
    ).render()


# ---------------------------------------------------------------------------
# Matrix posting
# ---------------------------------------------------------------------------
async def _post_summary(
    matrix_client, new_today: list[Candidate], total: int, today: str, report_path: Path
):
    if not matrix_client or not USER_ROOM:
        log.warning(
            "Skipping Matrix post: matrix_client=%s USER_ROOM=%s",
            bool(matrix_client),
            USER_ROOM,
        )
        return
    if not new_today:
        log.info("No new candidates today — skipping Matrix post per user preference.")
        return

    lines = [f"🏠 **SF apartment update — {today}**", ""]
    lines.append(f"{len(new_today)} new listing(s) today (of {total} active candidates):")
    for c in new_today[:5]:
        lines.append(f"- ${c.price:,} · {c.neighborhood} · {c.title[:70]}")
    lines.append("")
    lines.append("→ Dashboard: `_dashboards/sf-apartment-search.html`")
    lines.append(f"→ Today's report: `Projects/SF Apartment Search/{report_path.name}`")
    body = "\n".join(lines)

    try:
        await matrix_client.room_send(
            USER_ROOM,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": body},
        )
    except Exception as e:
        log.error("Failed to post Matrix summary: %s", e)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_daily_update(matrix_client=None) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    _ensure_dirs()
    candidates = await _fetch_candidates()
    log.info("apartment_search: %d candidates after filtering", len(candidates))

    new_today: list[Candidate] = []
    for c in candidates:
        _, wrote_new = _write_listing_md(c, today)
        if wrote_new:
            new_today.append(c)

    DASHBOARD_PATH.write_text(_build_dashboard(candidates, now))
    log.info("apartment_search: wrote dashboard to %s", DASHBOARD_PATH)

    report_path = PROJECT_DIR / f"{today}-findings.html"
    report_path.write_text(_build_report(candidates, new_today, today))
    log.info("apartment_search: wrote report to %s", report_path)

    await _post_summary(matrix_client, new_today, len(candidates), today, report_path)

    return {
        "today": today,
        "total_candidates": len(candidates),
        "new_today": len(new_today),
        "dashboard": str(DASHBOARD_PATH),
        "report": str(report_path),
    }
