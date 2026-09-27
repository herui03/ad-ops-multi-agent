"""Build docs/replay/index.html: a static, offline RECORDED REPLAY of the last E2E run.

It only re-displays docs/evidence/e2e/results.json and the screenshots taken by the real run.
It does not execute anything and is not a substitute for running the app.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.loads((ROOT / "docs/evidence/e2e/results.json").read_text())
out = ROOT / "docs/replay/index.html"
out.parent.mkdir(parents=True, exist_ok=True)
rows = []
for r in data["results"]:
    shots = r.get("screenshots") or ([r["screenshot"]] if r.get("screenshot") else [])
    imgs = "".join(f'<a href="../../{html.escape(s)}"><img src="../../{html.escape(s)}" alt="{html.escape(s)}"></a>'
                   for s in shots)
    rows.append(f'<section><h2>{"PASS" if r["pass"] else "FAIL"} · {html.escape(r["name"])}</h2>'
                f'<p>{html.escape(str(r.get("note", "")))}</p><div class="shots">{imgs}</div></section>')
s = data["summary"]
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>E2E Recorded Replay</title><style>
:root{{--bg:#f8fafc;--fg:#0f172a;--muted:#475569;--card:#fff;--line:#e2e8f0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f172a;--fg:#e2e8f0;--muted:#94a3b8;--card:#1e293b;--line:#334155}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
.banner{{border:2px solid #d97706;background:#fef3c7;color:#78350f;padding:8px 12px;border-radius:6px;font-weight:600}}
section{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0}}
h1{{font-size:20px}} h2{{font-size:15px;margin:0 0 4px}} p{{color:var(--muted);margin:0 0 8px;overflow-wrap:anywhere}}
.shots{{display:flex;flex-wrap:wrap;gap:8px}} img{{width:260px;max-width:100%;border:1px solid var(--line);border-radius:4px}}
</style></head><body>
<p class="banner">RECORDED REPLAY: static screenshots and results from one real Chromium run. Nothing on this page is live.</p>
<h1>Ad Ops approval gate: E2E evidence ({s['passed']}/{s['total']} checks passed)</h1>
<p>Browser: {html.escape(s['browser'])} · recorded {html.escape(s['when'])} · server: uvicorn in demo mode (deterministic provider, no network).</p>
{''.join(rows)}
</body></html>"""
out.write_text(page)
print(f"wrote {out.relative_to(ROOT)}")
