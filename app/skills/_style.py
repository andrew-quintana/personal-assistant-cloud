"""Shared CSS for dashboards and reports.

Self-contained, system-fonts, dark-mode aware. Surfing-friendly.
"""

BASE_CSS = """
:root {
  --bg:#fff; --fg:#1a1a1a; --muted:#6b6b6b;
  --accent:#2563eb; --border:#e5e5e5; --card:#fafafa;
  --good:#16a34a; --warn:#d97706; --bad:#dc2626;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0f1115; --fg:#e7e7e7; --muted:#9aa0a6;
    --accent:#60a5fa; --border:#2a2d33; --card:#161922;
  }
}
html,body { background:var(--bg); color:var(--fg); }
body {
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,system-ui,sans-serif;
  margin:0 auto; padding:2rem 2.5rem; line-height:1.55;
}
h1 { font-size:1.6rem; margin:0 0 .25rem; letter-spacing:-0.01em; }
.meta { color:var(--muted); font-size:.85rem; margin-bottom:2rem; }
h2 { font-size:1.15rem; margin:2rem 0 .75rem; }
h3 { font-size:1rem; margin:1.25rem 0 .4rem; }
.grid { display:grid; gap:1rem; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); margin-bottom:1.5rem; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1rem 1.1rem; }
.label { color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; }
.value { font-size:1.5rem; font-weight:600; margin-top:.25rem; }
.tldr { background:var(--card); border-left:3px solid var(--accent); padding:1rem 1.25rem; border-radius:6px; margin:1rem 0 1.5rem; }
table { width:100%; border-collapse:collapse; font-size:.9rem; }
th,td { text-align:left; padding:.55rem .75rem; border-bottom:1px solid var(--border); vertical-align:top; }
th { font-weight:600; color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; }
tr:hover td { background:var(--card); }
ul,ol { padding-left:1.4rem; } li { margin:.35rem 0; }
.pill { display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.75rem; border:1px solid var(--border); margin-right:.25rem; }
.pill.good { color:var(--good); border-color:color-mix(in srgb,var(--good) 40%,var(--border)); }
.pill.warn { color:var(--warn); border-color:color-mix(in srgb,var(--warn) 40%,var(--border)); }
.pill.bad { color:var(--bad); border-color:color-mix(in srgb,var(--bad) 40%,var(--border)); }
a { color:var(--accent); }
.muted { color:var(--muted); font-weight:400; font-size:.85rem; }
.source { font-size:.8rem; color:var(--muted); margin-top:3rem; padding-top:1rem; border-top:1px solid var(--border); }
"""


def html_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
