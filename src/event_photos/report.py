"""Static HTML report: kept photos (before/after), frames, rejects with reasons."""
from __future__ import annotations

from html import escape
from pathlib import Path

CSS = """
:root{--ink:#16181d;--muted:#5d636f;--line:#e4e6ea;--bg:#f7f7f5;--accent:#d4572a;--ok:#2f7d4f;--bad:#b3261e}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{padding:32px 40px 8px}h1{margin:0 0 4px;font-size:26px}h2{margin:40px 0 12px;font-size:19px}
main{padding:0 40px 60px}.muted{color:var(--muted)}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.stat{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:140px}
.stat b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.card .meta{padding:10px 12px;font-size:13px}
.ba{position:relative;aspect-ratio:3/2;background:#000}
.ba img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
.ba .after{opacity:1;transition:opacity .15s}.ba:hover .after{opacity:0}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:#eef0f3;margin-right:4px}
.reject .reason{color:var(--bad);font-weight:600}.flag{color:#9a6700;font-weight:600}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.frames img{width:100%;border-radius:6px;border:1px solid var(--line);background:#fff}
.reject img{width:100%;aspect-ratio:3/2;object-fit:cover;filter:grayscale(.4);display:block}
"""


def write_report(out_dir: Path, rows: list[dict], stats: dict, look: str) -> Path:
    kept = [r for r in rows if r["keep"]]
    review = [r for r in kept if r["flags"]]
    rejected = [r for r in rows if not r["keep"]]

    def stat(label: str, value) -> str:
        return f'<div class="stat"><b>{escape(str(value))}</b><span class="muted">{escape(label)}</span></div>'

    timings = " · ".join(f"{escape(k)}: {v:.1f}s" for k, v in stats["timings"].items())
    html = [f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>POC — Fotos do evento</title>
<style>{CSS}</style><header><h1>POC — Pipeline de fotos do evento</h1>
<div class="muted">Look: <b>{escape(look)}</b> · passe o mouse na foto para ver o original</div>
<div class="stats">{stat("fotos recebidas", stats["total"])}{stat("selecionadas", len(kept))}
{stat("para revisar", len(review))}{stat("descartadas", len(rejected))}{stat("sequências agrupadas", stats["burst_groups"])}
{stat("segundos por foto", f'{stats["seconds_per_photo"]:.1f}')}</div>
<p class="muted">{timings}</p></header><main>"""]

    html.append(f"<h2>Selecionadas ({len(kept)})</h2><p class='muted'>Primeiro as marcadas para revisar.</p><div class='grid'>")
    for r in sorted(kept, key=lambda r: not r["flags"]):
        adj = r["adjustments"]
        faces = len(r["analysis"]["faces"])
        html.append(f"""<div class="card"><div class="ba">
<img src="previews/before/{r['preview']}" alt=""><img class="after" src="previews/after/{r['preview']}" alt=""></div>
<div class="meta"><b>{escape(r['name'])}</b><br>
<span class="tag">IA {adj['strength']:.0%}</span><span class="tag">rostos: {faces}</span>
<span class="tag">nitidez {r['analysis']['sharpness']:.0f}</span>
{"".join(f'<br><span class="flag">{escape(f)}</span>' for f in r["flags"])}</div></div>""")
    html.append("</div>")

    html.append("<h2>Molduras</h2><div class='frames'>")
    frame = (stats.get("frames") or [{"key": ""}])[0]["key"]
    for r in kept:
        for fmt in ("feed", "story"):
            html.append(f'<img src="frames/{fmt}/{frame}/{r["output"]}" alt="{fmt}" loading="lazy">')
    html.append("</div>")

    html.append(f"<h2>Descartadas ({len(rejected)})</h2><div class='grid'>")
    for r in rejected:
        reasons = "<br>".join(escape(x) for x in r["reasons"])
        html.append(f"""<div class="card reject"><img src="previews/before/{r['preview']}" alt="">
<div class="meta"><b>{escape(r['name'])}</b><br><span class="reason">{reasons}</span></div></div>""")
    html.append("</div></main></html>")

    path = out_dir / "index.html"
    path.write_text("".join(html), encoding="utf-8")
    return path
