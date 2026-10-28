"""The event report for organizers and sponsors (`event-photos stats`), from the gallery's CloudFront logs.

What the logs hold and what the page counts: README, "Counts for the event report". Everything here is
counts of actions, never people: the logs carry no IP, port or cookie, and nothing ties a search to a photo.
The report is in Portuguese, like the gallery.
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import json
import re
import statistics
import subprocess
import urllib.request
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, unquote
from zoneinfo import ZoneInfo

from . import brand

# Link previews: one fetch of the preview card each time a gallery or photo link is pasted in an app.
PREVIEW_BOTS = re.compile(r"WhatsApp|facebookexternalhit|Facebot|LinkedInBot|Twitterbot|Slackbot|TelegramBot|"
                          r"Discordbot|SkypeUriPreview|redditbot|Iframely|Embedly", re.I)
OTHER_BOTS = re.compile(r"bot\b|bot/|crawl|spider|slurp|curl/|wget/|python|Go-http-client|okhttp|HeadlessChrome|"
                        r"Lighthouse|monitor", re.I)
PHONE = re.compile(r"iPhone|Mobile|Windows Phone", re.I)
SERVED = {"200", "206", "304"}
HIGHLIGHTS = 12
WALL_PING = 15  # minutes between the venue screen's `e=wall` counts (wall.py)
FIND_BUCKETS = ("0", "1-5", "6+", "erro")
KEEP_ROWS = 15  # printed, a table up to this long never splits across pages


@dataclass(frozen=True)
class Hit:
    when: dt.datetime  # in the event's time zone
    path: str
    query: dict[str, str]
    status: str
    bytes: int
    agent: str  # "person", "preview" or "bot"
    phone: bool


def agent_kind(user_agent: str) -> str:
    if PREVIEW_BOTS.search(user_agent):
        return "preview"
    if OTHER_BOTS.search(user_agent) or user_agent in ("", "-"):
        return "bot"
    return "person"


def parse_line(line: str, tz: ZoneInfo) -> Hit | None:
    """One JSON record of CloudFront standard logging v2; None for lines that are not records."""
    try:
        r = json.loads(line)
        when = dt.datetime.fromisoformat(f"{r['date']}T{r['time']}+00:00").astimezone(tz)
    except (ValueError, KeyError, TypeError):
        return None
    ua = unquote(r.get("cs(User-Agent)", "-"))
    query = r.get("cs-uri-query", "-")
    return Hit(when, r.get("cs-uri-stem", ""), dict(parse_qsl(query)) if query not in ("", "-") else {},
               str(r.get("sc-status", "")), int(r.get("sc-bytes", 0) or 0), agent_kind(ua), bool(PHONE.search(ua)))


def read_logs(folder: Path, tz: ZoneInfo, since: dt.date | None = None, until: dt.date | None = None) -> list[Hit]:
    hits = []
    for path in sorted(folder.rglob("*.gz")):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                hit = parse_line(line, tz)
                if hit and (not since or hit.when.date() >= since) and (not until or hit.when.date() <= until):
                    hits.append(hit)
    return sorted(hits, key=lambda h: h.when)


def read_rounds(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _photo_id(path: str, folder: str, suffix: str) -> str | None:
    if path.startswith(f"/{folder}/") and path.endswith(suffix):
        return path[len(folder) + 2:-len(suffix)]
    return None


def compute(hits: list[Hit], listing: dict, rounds: list[dict], taken: dict[str, dt.datetime],
            frames: dict[str, str], excluded: set[str]) -> dict:
    """All the report's numbers. `listing` is the published photos.json; `taken`, photo id → capture time in the
    event's time zone; `frames`, design key → label; `excluded`, photos kept out of the highlights (minors)."""
    photos = listing.get("photos", [])
    moments = [m["n"] for m in listing.get("moments", [])]
    events = [h for h in hits if h.path == "/e.gif" and h.status in SERVED and h.agent != "bot" and "e" in h.query]
    by = Counter(h.query["e"] for h in events)

    def of(name: str) -> list[Hit]:
        return [h for h in events if h.query["e"] == name]

    opens = of("open")
    per_day = Counter(h.when.date().isoformat() for h in opens)
    per_hour = Counter(h.when.strftime("%Y-%m-%d %H:00") for h in opens)
    peak = max(per_hour.items(), key=lambda kv: kv[1]) if per_hour else None

    kept = of("save") + of("share")
    by_format = Counter(h.query.get("m", "") for h in kept)
    by_frame = Counter(frames.get(h.query.get("f", ""), "Divertida" if h.query.get("f") == "fun"
                                  else "Sem moldura" if not h.query.get("f") else h.query["f"]) for h in kept)
    finds = of("find")

    served = [h for h in hits if h.status in SERVED]
    pasted = [h for h in served if h.agent == "preview"
              and (h.path == "/og.jpg" or _photo_id(h.path, "og", ".jpg"))]
    link_visits = [h for h in served if h.agent == "person" and _photo_id(h.path, "p", ".html")]

    opened = Counter(h.query.get("id", "") for h in of("photo"))
    spread = Counter(h.query.get("id", "") for h in kept + of("link"))
    known = {p["id"]: p for p in photos}

    def top(counter: Counter) -> list[dict]:
        ranked = [(pid, n) for pid, n in counter.most_common() if pid in known and pid not in excluded]
        return [{"id": pid, "n": n, "moment": moments[known[pid]["m"]] if known[pid]["m"] < len(moments) else "",
                 "time": known[pid].get("t", ""), "by": known[pid].get("c", "")} for pid, n in ranked[:HIGHLIGHTS]]

    round_rows = []
    for r in rounds:
        published = dt.datetime.fromisoformat(r["published"])
        waits = [(published - taken[i]).total_seconds() / 60 for i in r["new"]
                 if i in taken and dt.timedelta(0) <= published - taken[i] <= dt.timedelta(days=1)]
        round_rows.append({"published": r["published"], "new": len(r["new"]), "total": r["total"],
                           "uploads": r["uploads"], "median_minutes": round(statistics.median(waits)) if waits else None})

    credits = Counter(p.get("c", "") for p in photos if p.get("c"))
    return {
        "period": {"first": hits[0].when.isoformat(timespec="minutes") if hits else None,
                   "last": hits[-1].when.isoformat(timespec="minutes") if hits else None},
        "day": {"published": len(photos), "received": rounds[-1]["uploads"] if rounds else None,
                "photographers": dict(credits.most_common()), "rounds": round_rows},
        "reach": {"opens": len(opens), "per_day": dict(sorted(per_day.items())),
                  "per_hour": dict(sorted(per_hour.items())),
                  "peak": {"hour": peak[0], "opens": peak[1]} if peak else None,
                  "photo_views": by["photo"], "photos_viewed": len(opened), "link_visits": len(link_visits),
                  "phone": sum(h.phone for h in opens), "computer": sum(not h.phone for h in opens)},
        "brand": {"saved": by["save"], "shared": by["share"], "by_format": dict(by_format.most_common()),
                  "by_frame": dict(by_frame.most_common()), "frame_picks": by["frame"],
                  "fun_picks": sum(h.query.get("f") == "fun" for h in of("frame")), "rerolls": by["reroll"],
                  "tag_copied": by["tag"], "links_sent": by["link"], "links_pasted": len(pasted),
                  "new_photos_taps": by["new"]},
        "find": {"searches": len(finds), "by_result": {k: sum(h.query.get("n") == k for h in finds) for k in FIND_BUCKETS},
                 "camera": sum(h.query.get("s", "cam") == "cam" for h in finds),
                 "photo": sum(h.query.get("s") == "file" for h in finds)},
        "venue": {"wall_hours": round(by["wall"] * WALL_PING / 60, 1)},
        "highlights": {"opened": top(opened), "spread": top(spread)},
        "cost": {"gb_served": round(sum(h.bytes for h in hits) / 1e9, 2), "requests": len(hits)},
    }


# --- the page ----------------------------------------------------------------------------------------------------

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#091b33;font:15px/1.5 FONT;-webkit-font-smoothing:antialiased}
header{background:var(--navy);color:#fff;padding:28px 40px}header img{height:56px;display:block;margin-bottom:14px}
header h1{margin:0;font-size:28px;letter-spacing:-.02em}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1040px;margin:0 auto;padding:12px 40px 48px}
h2{margin:36px 0 6px;font-size:21px;letter-spacing:-.01em;border-bottom:3px solid var(--orange);width:fit-content}
.lead{color:#4a5568;margin:4px 0 14px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.stat{background:#fff;border:1px solid #e2e5eb;border-radius:12px;padding:12px 14px;break-inside:avoid}
.stat b{display:block;font-size:28px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--navy)}
.stat span{color:#4a5568;font-size:13px}
table{border-collapse:collapse;width:100%;margin-top:12px;background:#fff;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #e2e5eb;font-size:14px}th{color:#4a5568;font-weight:600}
td.n,th.n{text-align:right}.bar{display:inline-block;height:10px;background:var(--orange);border-radius:3px;vertical-align:middle}
.photos{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px}
.photos figure{margin:0;background:#fff;border:1px solid #e2e5eb;border-radius:10px;overflow:hidden;break-inside:avoid}
.photos img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}
.photos figcaption{padding:6px 8px;font-size:12px;color:#4a5568}.photos figcaption b{color:var(--navy)}
.notes{background:#fff;border-left:4px solid var(--orange);padding:12px 16px;margin-top:14px;font-size:14px}
.notes li{margin:4px 0}
.cover{padding-top:20px}.cover .stats{grid-template-columns:repeat(4,1fr)}.cover .stat b{font-size:34px}
.chart{background:#fff;border:1px solid #e2e5eb;border-radius:12px;padding:14px 16px 10px;margin-top:12px;break-inside:avoid}
.chart h3{margin:0 0 2px;font-size:15px}.chart p{margin:0 0 8px;color:#4a5568;font-size:13px}
.chart svg{display:block;width:100%;height:auto;overflow:visible}.chart svg text{font:14px FONT;fill:#4a5568}
.chart svg .v{fill:#091b33;font-weight:700}.col{fill:var(--orange)}.col:hover{fill:#d96f0b}
.rows{display:grid;grid-template-columns:max-content 1fr max-content;gap:6px 12px;align-items:center;font-size:14px}
.rows i{display:block;height:14px;background:var(--orange);border-radius:0 4px 4px 0;min-width:2px}
.rows b{font-variant-numeric:tabular-nums;text-align:right}
h3{font-size:16px;margin:18px 0 0}
@media print{body{background:#fff}header,.bar,.col,.rows i{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .cover{break-after:page}tr,.stats,.notes,.keep{break-inside:avoid}}
""".replace("FONT", brand.FONT_STACK)


def _n(value) -> str:
    return "—" if value is None else f"{value:,}".replace(",", ".")


def _stat(value, label: str) -> str:
    return f'<div class="stat"><b>{escape(_n(value) if not isinstance(value, str) else value)}</b><span>{escape(label)}</span></div>'


def _table(head: tuple[str, ...], rows: list[tuple], bars: int | None = None) -> str:
    """`bars`: index of a numeric column drawn as a bar too."""
    if not rows:
        return '<p class="lead">Sem registros.</p>'
    top = max((r[bars] for r in rows), default=0) if bars is not None else 0
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            if isinstance(v, (int, float)) or v is None:
                bar = (f' <span class="bar" style="width:{max(2, round(80 * v / top))}px"></span>'
                       if i == bars and top and v else "")
                cells.append(f'<td class="n">{_n(v)}{bar}</td>')
            else:
                cells.append(f"<td>{escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    numeric = [isinstance(v, (int, float)) or v is None for v in rows[0]]
    whole = ' class="keep"' if len(rows) <= KEEP_ROWS else ""  # a short table moves to the next page whole
    return (f"<table{whole}><thead><tr>"
            + "".join(f'<th{" class=n" if k else ""}>{escape(h)}</th>' for h, k in zip(head, numeric))
            + "</tr></thead>" + "".join(body) + "</table>")


def _hours(per_hour: dict[str, int], per_day: dict[str, int]) -> list[tuple[str, str, int]]:
    """Opens on a continuous time axis, empty hours included, as (axis label, tooltip label, opens). Past two days
    an hourly axis gets too dense, so it turns into one column per day."""
    if not per_hour:
        return []
    first, last = (dt.datetime.strptime(h, "%Y-%m-%d %H:00") for h in (min(per_hour), max(per_hour)))
    if last - first > dt.timedelta(hours=48):
        start, end = (dt.date.fromisoformat(d) for d in (min(per_day), max(per_day)))
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        return [(d.strftime("%d/%m"), d.strftime("%d/%m"), per_day.get(d.isoformat(), 0)) for d in days]
    out, at, day = [], first, None
    while at <= last:
        label = f"{at:%Hh}" if at.date() == day else f"{at:%d/%m %Hh}"
        day = at.date()
        out.append((label, f"{at:%d/%m %Hh}", per_hour.get(at.strftime("%Y-%m-%d %H:00"), 0)))
        at += dt.timedelta(hours=1)
    return out


def _columns(points: list[tuple[str, str, int]], unit: tuple[str, str]) -> str:
    """A column chart in plain SVG: one value label on the peak, the rest on hover. `unit`: singular and plural."""
    if not points:
        return '<p class="lead">Sem registros.</p>'
    width, height, top, bottom = 960, 260, 24, 30
    slot = width / len(points)
    gap = min(8, slot * .25)
    peak = max(n for *_, n in points) or 1
    every = -(-len(points) // 12)  # at most 12 axis labels
    marks, labels = [], []
    for i, (axis, tip, n) in enumerate(points):
        x, w = i * slot + gap / 2, slot - gap
        h = (height - top - bottom) * n / peak
        y = height - bottom - h
        r = min(4, w / 2, h)
        if n:
            marks.append(f'<path class="col" d="M{x:.1f} {height - bottom}V{y + r:.1f}q0 -{r:.1f} {r:.1f} -{r:.1f}'
                         f'h{w - 2 * r:.1f}q{r:.1f} 0 {r:.1f} {r:.1f}V{height - bottom}z">'
                         f'<title>{escape(tip)}: {_n(n)} {unit[n != 1]}</title></path>')
        if n == peak:
            marks.append(f'<text class="v" x="{x + w / 2:.1f}" y="{y - 7:.1f}" text-anchor="middle">{_n(n)}</text>')
        if i % every == 0:
            labels.append(f'<text x="{x + w / 2:.1f}" y="{height - bottom + 20}" text-anchor="middle">{escape(axis)}</text>')
    axis = f'<line x1="0" x2="{width}" y1="{height - bottom}" y2="{height - bottom}" stroke="#c9ced8"/>'
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Gráfico de colunas">'
            f'{axis}{"".join(marks)}{"".join(labels)}</svg>')


def _rows(items: list[tuple[str, int]]) -> str:
    """Horizontal bars with the label left and the value right."""
    top = max((n for _, n in items), default=0) or 1
    return '<div class="rows">' + "".join(
        f'<span>{escape(k)}</span><i style="width:{100 * n / top:.1f}%"></i><b>{_n(n)}</b>' for k, n in items) + "</div>"


def _cover(day: dict, reach: dict, brand_: dict, find: dict) -> str:
    spread = brand_["saved"] + brand_["shared"]
    return f"""<section class="cover"><div class="stats">{_stat(day['published'], 'fotos publicadas')}
{_stat(reach['opens'], 'aberturas da galeria')}{_stat(reach['photo_views'], 'fotos abertas')}
{_stat(spread, 'fotos baixadas ou compartilhadas')}</div>
<div class="chart"><h3>Aberturas da galeria ao longo do tempo</h3><p>Quando as pessoas entraram na galeria.</p>
{_columns(_hours(reach['per_hour'], reach['per_day']), ('abertura', 'aberturas'))}</div>
<div class="chart"><h3>O que as pessoas fizeram</h3><p>Ações registradas na galeria; cada uma conta uma vez por toque.</p>
{_rows([('Abriram a galeria', reach['opens']), ('Abriram uma foto', reach['photo_views']),
        ('Escolheram uma moldura', brand_['frame_picks']), ('Trocaram os stickers', brand_['rerolls']),
        ('Baixaram ou compartilharam', spread), ('Enviaram o link de uma foto', brand_['links_sent']),
        ('Buscaram pelo rosto', find['searches'])])}</div></section>"""


def _minutes(m: int | None) -> str:
    return "—" if m is None else f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _when(iso: str | None) -> str:
    return dt.datetime.fromisoformat(iso).strftime("%d/%m %H:%M") if iso else "—"


def _photos(items: list[dict], thumbs: dict[str, bytes], unit: tuple[str, str]) -> str:
    """`unit`: singular and plural."""
    if not items:
        return '<p class="lead">Sem registros.</p>'
    figures = []
    for p in items:
        img = (f'<img src="data:image/webp;base64,{base64.b64encode(thumbs[p["id"]]).decode()}" alt="">'
               if p["id"] in thumbs else "")
        caption = " · ".join(x for x in (p["moment"], p["time"]) if x)
        figures.append(f"<figure>{img}<figcaption><b>{_n(p['n'])} {unit[p['n'] != 1]}</b><br>{escape(caption)}</figcaption></figure>")
    return '<div class="photos">' + "".join(figures) + "</div>"


def render(event: dict, numbers: dict, thumbs: dict[str, bytes]) -> str:
    art = brand.assets()
    day, reach, brand_, find, venue, cost = (numbers[k] for k in ("day", "reach", "brand", "find", "venue", "cost"))
    received = f" de {_n(day['received'])} recebidas" if day["received"] else ""
    rounds = [(_when(r["published"]), r["new"], r["total"],
               _minutes(r["median_minutes"])) for r in day["rounds"]]
    peak = reach["peak"]
    per_hour = [(dt.datetime.strptime(h, "%Y-%m-%d %H:00").strftime("%d/%m %Hh"), n) for h, n in reach["per_hour"].items()]
    found = find["by_result"]
    sections = [
        f"""<section><div class="keep"><h2>O dia em números</h2>
<div class="stats">{_stat(day['published'], f'fotos publicadas{received}')}{_stat(len(day['photographers']) or None, 'fotógrafos voluntários')}
{_stat(len(day['rounds']) or None, 'rodadas de publicação')}</div></div>
{_table(('Fotógrafo', 'Fotos'), list(day['photographers'].items()), bars=1) if day['photographers'] else ''}
<div class="keep"><p class="lead">Rodadas: quando cada leva de fotos chegou à galeria e o tempo mediano entre a foto e
a publicação.</p>{_table(('Publicada', 'Fotos novas', 'Total na galeria', 'Da foto à galeria'), rounds)}</div></section>""",
        f"""<section><div class="keep"><h2>Alcance</h2>
<div class="stats">{_stat(reach['opens'], 'aberturas da galeria')}{_stat(f"{peak['opens']} às {peak['hour'][-5:-3]}h" if peak else '—', 'pico em uma hora')}
{_stat(reach['photo_views'], 'fotos abertas')}{_stat(reach['photos_viewed'], 'fotos diferentes vistas')}
{_stat(reach['link_visits'], 'visitas vindas de link de foto')}{_stat(reach['phone'], 'aberturas no celular')}
{_stat(reach['computer'], 'aberturas no computador')}</div></div>
{_table(('Hora', 'Aberturas'), per_hour, bars=1)}</section>""",
        f"""<section class="keep"><h2>Marca em circulação</h2>
<p class="lead">Cada foto baixada ou compartilhada leva a moldura e a marca do evento.</p>
<div class="stats">{_stat(brand_['saved'], 'fotos baixadas')}{_stat(brand_['shared'], 'fotos compartilhadas')}
{_stat(brand_['fun_picks'], 'vezes na moldura Divertida')}{_stat(brand_['rerolls'], 'trocas de stickers')}
{_stat(brand_['tag_copied'], '@ do evento copiado')}{_stat(brand_['links_sent'], 'links de foto enviados')}
{_stat(brand_['links_pasted'], 'links colados em apps')}</div>
{_table(('Formato', 'Baixadas e compartilhadas'), [({'feed': 'Post', 'story': 'Story'}.get(k, k or 'Original'), n) for k, n in brand_['by_format'].items()], bars=1)}
{_table(('Moldura', 'Baixadas e compartilhadas'), list(brand_['by_frame'].items()), bars=1)}</section>""",
        f"""<section class="keep"><h2>Encontrar-se</h2>
<div class="stats">{_stat(find['searches'], 'buscas por rosto')}{_stat(found['1-5'] + found['6+'], 'acharam fotos')}
{_stat(find['camera'], 'com a câmera')}{_stat(find['photo'], 'com uma foto do celular')}</div>
{_table(('Resultado', 'Buscas'), [('Nenhuma foto', found['0']), ('1 a 5 fotos', found['1-5']), ('6 fotos ou mais', found['6+']), ('Erro ou recusa', found['erro'])], bars=1)}</section>""",
        f"""<section class="keep"><h2>No local</h2>
<div class="stats">{_stat(f"{venue['wall_hours']:g} h".replace('.', ','), 'de telão no ar')}{_stat(brand_['new_photos_taps'], 'toques em "Chegaram fotos novas"')}</div></section>""",
        f"""<section><div class="keep"><h2>Destaques</h2>
<p class="lead">As fotos mais abertas e as mais espalhadas (baixadas, compartilhadas ou com link enviado). Fotos com
menores de idade ficam de fora.</p>
<h3>Mais abertas</h3>{_photos(numbers['highlights']['opened'], thumbs, ('abertura', 'aberturas'))}</div>
<div class="keep"><h3>Mais espalhadas</h3>{_photos(numbers['highlights']['spread'], thumbs, ('vez', 'vezes'))}</div></section>""",
        f"""<section class="keep"><h2>Custo e limites</h2>
<div class="stats">{_stat(f"{cost['gb_served']:g} GB".replace('.', ','), 'servidos pela galeria')}{_stat(cost['requests'], 'pedidos registrados')}</div>
<ul class="notes"><li>São contagens de ações, não de pessoas: a galeria não guarda identificador de quem visita, e o
registro não tem IP.</li><li>Salvar a foto tocando e segurando a imagem não gera registro; um compartilhamento cancelado
não conta.</li><li>Links colados em apps contam as prévias pedidas por WhatsApp, LinkedIn e afins: uma mesma colagem pode
gerar mais de uma prévia, e um link já colado antes pode não gerar nenhuma.</li><li>Horas de telão: um registro a cada
{WALL_PING} minutos por tela aberta.</li><li>Robôs conhecidos ficam de fora das contagens de visitas.</li></ul></section>""",
    ]
    period = f"{_when(numbers['period']['first'])} a {_when(numbers['period']['last'])}"
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Relatório — {escape(event['name'])}</title>
<style>{brand.font_face(art['font'])}{brand.TOKENS}{CSS}</style>
<header><img src="{art['logo']}" alt="{escape(brand.LOGO_ALT)}"><h1>Relatório da galeria de fotos</h1>
<p>{escape(event['name'])} · registros de {escape(period)}</p></header>
<main>{_cover(day, reach, brand_, find)}{''.join(sections)}</main></html>"""


# --- fetching ----------------------------------------------------------------------------------------------------

def download_logs(bucket: str, dest: Path, profile: str) -> None:
    """Only what is not here yet: `s3 sync` skips files already downloaded."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["aws", "--profile", profile, "s3", "sync", f"s3://{bucket}/", str(dest), "--only-show-errors"],
                   check=True)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()
