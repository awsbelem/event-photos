"""Static public gallery for attendees, grouped by the moments of the event schedule.

The site is plain files (no server, no database), served by Cloudflare Pages or S3 + CloudFront:
the photographer's machine only uploads, nothing is ever served from it.
Page text is user-facing, so it is in Portuguese.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import shutil
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PIL import Image

from .frames import FRAMES_DIR

FRAME_FORMATS = ("feed", "story")
ASSET_FOLDERS = ("thumbs", "view", "photos", *FRAME_FORMATS)  # never change once published
THUMB_LONG_SIDE = 640
VIEW_LONG_SIDE = 1800
OTHER_MOMENT = "Outros momentos"
OWNER_SEP = "--"
SCHEDULE_ADVISED_ABOVE = 60  # photos; past this, one long scroll is hard to search for yourself
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]


@dataclass(frozen=True)
class Moment:
    start: dt.time
    title: str


@dataclass
class GalleryPhoto:
    id: str
    source: Path
    taken: dt.datetime | None
    width: int = 0
    height: int = 0
    moment: str = OTHER_MOMENT
    frames: tuple[str, ...] = ()
    by: str = ""  # photographer's name, when the event has several


LOCAL_SUFFIX = ".local.json"  # event.local.json: gitignored values (removal contact, face_search on/off)


def local_path(path: Path) -> Path:
    return path.with_name(path.stem + LOCAL_SUFFIX)


def merge_event(base: dict, local: dict) -> dict:
    """event.json overlaid with event.local.json; nested blocks (face_search) merge key by key."""
    merged = dict(base)
    for key, value in local.items():
        merged[key] = {**base[key], **value} if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return merged


def load_event(path: Path) -> dict:
    event = json.loads(path.read_text())
    if (local := local_path(path)).exists():
        event = merge_event(event, json.loads(local.read_text()))
    if isinstance(event.get("credits"), str):  # path to a CREDITS.json, relative to the event file
        event["credits"] = json.loads((path.parent / event["credits"]).read_text())
    event["moments"] = sorted((Moment(dt.time.fromisoformat(m["time"]), m["title"]) for m in event.get("schedule", [])),
                              key=lambda m: m.start)
    return event


def parse_offset(text: str) -> dt.timedelta:
    """'-0:05' → minus five minutes: how far the camera clock was ahead or behind."""
    hours, _, minutes = text.lstrip("+-").partition(":")
    offset = dt.timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
    return -offset if text.startswith("-") else offset


def owner_of(photo_id: str) -> str:
    """Inbox names are <photographer slug>--<original stem>; older runs have no owner."""
    owner, sep, _ = photo_id.partition(OWNER_SEP)
    return owner if sep else ""


def moment_for(taken: dt.datetime | None, moments: list[Moment]) -> str:
    """The last schedule entry started before the photo; earlier photos go to the first one."""
    if taken is None or not moments:
        return OTHER_MOMENT
    current = moments[0].title
    for m in moments:
        if taken.time() >= m.start:
            current = m.title
    return current


def _render_sizes(photo: GalleryPhoto, site: Path, designs: list[str]) -> GalleryPhoto:
    with Image.open(photo.source) as im:
        im = im.convert("RGB")
        photo.width, photo.height = im.size
        for folder, long_side, quality in (("thumbs", THUMB_LONG_SIDE, 72), ("view", VIEW_LONG_SIDE, 82)):
            copy = im.copy()
            copy.thumbnail((long_side, long_side), Image.LANCZOS)
            copy.save(site / folder / f"{photo.id}.webp", "WEBP", quality=quality, method=5)
    shutil.copyfile(photo.source, site / "photos" / f"{photo.id}.jpg")
    frames = []
    for fmt in FRAME_FORMATS:  # already 1080 px wide: served as is, for viewing and download
        made = [d for d in designs if (photo.source.parent.parent / "frames" / fmt / d / photo.source.name).exists()]
        if designs and made == designs:
            for d in designs:
                (site / fmt / d).mkdir(exist_ok=True)
                shutil.copyfile(photo.source.parent.parent / "frames" / fmt / d / photo.source.name,
                                site / fmt / d / f"{photo.id}.jpg")
            frames.append(fmt)
    photo.frames = tuple(frames)
    return photo


def build_gallery(run_dir: Path, site: Path, event: dict, clock_offset: dt.timedelta = dt.timedelta(),
                  workers: int = 8) -> Path:
    metrics = json.loads((run_dir / "metrics.json").read_text())
    rows = [r for r in metrics["photos"] if r["keep"]]
    designs = metrics["stats"].get("frames", [])
    if site.exists():
        shutil.rmtree(site)
    for folder in ASSET_FOLDERS:
        (site / folder).mkdir(parents=True)

    names = event.get("photographers", {})  # {slug: name}
    offsets = {slug: parse_offset(o) for slug, o in event.get("clock_offsets", {}).items()}
    photos = []
    for r in rows:
        pid = Path(r["output"]).stem
        owner = owner_of(pid)
        taken = (dt.datetime.fromisoformat(r["capture_time"]) + clock_offset + offsets.get(owner, dt.timedelta())
                 if r["capture_time"] else None)
        photos.append(GalleryPhoto(pid, run_dir / "selected" / r["output"], taken,
                                   moment=moment_for(taken, event["moments"]),
                                   by=names.get(owner, "") if len(names) > 1 else ""))
    with ThreadPoolExecutor(workers) as pool:
        photos = list(pool.map(lambda p: _render_sizes(p, site, [d["key"] for d in designs]), photos))
    photos.sort(key=lambda p: (p.taken or dt.datetime.max, p.id))
    if not event["moments"] and len(photos) > SCHEDULE_ADVISED_ABOVE:
        print(f"aviso: {len(photos)} fotos sem \"schedule\" no evento — a galeria fica numa rolagem só, "
              "sem atalhos por momento")

    (site / "index.html").write_text(_page(event, photos, designs), encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    # Cloudflare Pages headers (CloudFront sets the same ones in infra/aws-gallery.yaml):
    # keep the gallery out of search engines and out of other sites' frames; photos never change.
    (site / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n"
                                   "  X-Frame-Options: DENY\n  Content-Security-Policy: frame-ancestors 'none'\n"
                                   + "".join(f"/{folder}/*\n  Cache-Control: public, max-age=31536000, immutable\n"
                                             for folder in ASSET_FOLDERS))
    return site / "index.html"


def _date_pt(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    keep = "".join(c.lower() if c.isalnum() else "-" for c in ascii_text)
    return "-".join(part for part in keep.split("-") if part)


BACKGROUND = "#0d1117"
_ICONS = {  # authored strokes, one weight, so no glyph depends on the visitor's fonts
    "prev": '<path d="M15 5l-7 7 7 7"/>', "next": '<path d="M9 5l7 7-7 7"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>', "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
}


def _script_json(value, **kwargs) -> str:
    """JSON for inside <script>: no "</script>" (or "<!--") in a name or title can end the block early."""
    return json.dumps(value, ensure_ascii=False, **kwargs).replace("<", "\\u003c")


def _icon(name: str) -> str:
    return (f'<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>')


def _credits(credits: list[dict], shown: list[str]) -> str:
    """Attribution for third-party photos (Creative Commons); list numbers match the viewer's "N de M"."""
    by_id = {Path(c["file"]).stem: c for c in credits}
    items = "".join(
        f'<li><a href="{escape(c["page"])}" rel="noopener">{escape(c["author"])}</a>, '
        f'<a href="{escape(c["license_url"])}" rel="noopener license">{escape(c["license"])}</a></li>'
        for pid in shown if (c := by_id.get(pid)))
    if not items:
        return ""
    return ("<details><summary>Créditos das fotos</summary><ol>" + items + "</ol>"
            "<p>Fotos via Wikimedia Commons. As versões tratadas e com moldura seguem a mesma licença da original.</p>"
            "</details>")


def _alt(p: GalleryPhoto, i: int, total: int) -> str:
    parts = [f"Foto {i} de {total}"]
    if p.moment != OTHER_MOMENT:
        parts.append(p.moment)
    if p.taken:
        parts.append(p.taken.strftime("%H:%M"))
    if p.by:
        parts.append(f"foto de {p.by}")
    return " · ".join(parts)


def _swatch(key: str) -> str:
    """The frame's sample as an inline image, so the chooser costs no extra request."""
    path = FRAMES_DIR / key / "swatch.png"
    if not path.exists():
        return ""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((96, 120), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=80)
    return f'<img src="data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode()}" alt="" width="{im.width}" height="{im.height}">'


def _modes(designs: list[dict]) -> str:
    """One button per frame (with its sample when there are several), then the bare photo."""
    many = len(designs) > 1
    buttons = "".join(
        f'<button data-mode="{escape(d["key"])}" aria-pressed="{str(i == 0).lower()}">'
        + (f'{_swatch(d["key"])}<span>{escape(d["label"])}</span>' if many else "Com moldura") + "</button>"
        for i, d in enumerate(designs))
    return (f'<div class="modes{" many" if many else ""}" role="group" aria-label="Moldura" '
            f'style="--n:{len(designs) + 1}">{buttons}<button data-mode="photo" aria-pressed="false">'
            + ('<span class="none" aria-hidden="true"></span><span>Sem moldura</span>' if many else "Sem moldura")
            + "</button></div>")


FINDER_CSS = """
.find-me{margin-top:14px;max-width:320px}
.tile[hidden],section[hidden],.chip[hidden],.found[hidden],.finder[hidden],[data-step][hidden]{display:none}
.found{max-width:1400px;margin:16px auto 0;padding:14px 20px;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
.found h2{margin:0;font-size:20px}.found p{margin:0;color:var(--muted);flex-basis:100%}
.found:focus{outline:none}.found .btn{flex:none;min-height:44px}
.finder{position:fixed;inset:0;z-index:40;background:#000c;display:grid;place-items:center;padding:16px}
.finder-box{width:100%;max-width:460px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}
.finder-box h2{margin:0 0 12px;font-size:20px}
.finder-box p{color:var(--muted);margin:0 0 12px}
.consent{display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid var(--line);border-radius:12px;
  color:var(--ink);margin-bottom:12px;cursor:pointer}
.consent input{width:22px;height:22px;flex:none;margin-top:2px}
.finder-small{font-size:13px}
.finder-actions{display:flex;gap:8px;margin-top:8px}
.finder video{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:12px;background:#000;transform:scaleX(-1)}
.finder-busy{font-size:17px;color:var(--ink)!important;padding:24px 0;text-align:center}
.finder-message{color:var(--ink)!important}
"""

FINDER_JS = """
(()=>{const cfg=FINDER;if(!cfg)return;
const dlg=document.querySelector(".finder"),btn=document.querySelector(".find-me"),bar=document.querySelector(".found"),
  consent=dlg.querySelector("#consent"),openCam=dlg.querySelector(".open-cam"),shoot=dlg.querySelector(".shoot"),
  video=dlg.querySelector("video"),msg=dlg.querySelector(".finder-message"),steps=[...dlg.querySelectorAll("[data-step]")];
let stream=null,last=null;
const step=n=>{steps.forEach(s=>s.hidden=s.dataset.step!==n);const f=dlg.querySelector("[data-step='"+n+"'] .primary");f&&f.focus();};
const stop=()=>{if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}video.srcObject=null;};
const tell=t=>{msg.textContent=t;step("message");};
function openDlg(){last=document.activeElement;consent.checked=false;openCam.disabled=true;step("consent");dlg.hidden=false;
  document.body.style.overflow="hidden";behind.forEach(e=>e.inert=true);consent.focus();}
function closeDlg(){stop();dlg.hidden=true;document.body.style.overflow="";behind.forEach(e=>e.inert=false);last&&last.focus();}
btn.onclick=openDlg;dlg.querySelectorAll(".finder-close").forEach(b=>b.onclick=closeDlg);
consent.onchange=()=>openCam.disabled=!consent.checked;
async function camera(){
  try{stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"user"},audio:false});}
  catch(e){tell("Não conseguimos abrir a câmera. Permita o acesso à câmera nas configurações do navegador ou veja as fotos por momento.");return;}
  video.srcObject=stream;await video.play().catch(()=>{});step("camera");}
openCam.onclick=()=>{if(consent.checked)camera();};dlg.querySelector(".retry").onclick=camera;
shoot.onclick=async()=>{const w=video.videoWidth,h=video.videoHeight;if(!w)return;
  const k=Math.min(1,640/Math.max(w,h)),c=document.createElement("canvas");c.width=Math.round(w*k);c.height=Math.round(h*k);
  c.getContext("2d").drawImage(video,0,0,c.width,c.height);stop();step("busy");
  const image=c.toDataURL("image/jpeg",0.85).split(",")[1];
  try{const r=await fetch(cfg.url+"search",{method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({consent:true,image})});
    const data=await r.json().catch(()=>({error:"Busca indisponível agora. Tente de novo em instantes."}));
    if(!r.ok){tell(data.error);return;}
    const ids=new Set(data.photos.map(x=>cfg.ids[x]||x));
    if(!PHOTOS.some(p=>ids.has(p.id))){tell(data.message||"Ainda não achamos fotos suas.");return;}
    closeDlg();filter(ids,data.note);}
  catch(e){tell("Sem conexão com a busca. Verifique a internet e tente de novo.");}};
function filter(ids,note){VIEW=PHOTOS.filter(p=>ids.has(p.id));
  document.querySelectorAll(".tile").forEach(t=>t.hidden=!ids.has(t.dataset.id));
  document.querySelectorAll("main section").forEach(s=>s.hidden=!s.querySelector(".tile:not([hidden])"));
  document.querySelectorAll(".chip").forEach(c=>{const s=document.getElementById(c.hash.slice(1)),n=c.querySelector("span");
    n.dataset.all=n.dataset.all||n.textContent;n.textContent=s?s.querySelectorAll(".tile:not([hidden])").length:n.dataset.all;
    c.hidden=!!(s&&s.hidden);});
  bar.querySelector("h2").textContent="Encontramos "+VIEW.length+(VIEW.length===1?" foto com você":" fotos com você");
  bar.querySelector("p").textContent=note||"";bar.hidden=false;bar.focus();}
bar.querySelector(".show-all").onclick=()=>{VIEW=PHOTOS;
  document.querySelectorAll(".tile,main section,.chip").forEach(e=>e.hidden=false);
  document.querySelectorAll(".chip span[data-all]").forEach(n=>n.textContent=n.dataset.all);bar.hidden=true;btn.focus();};
document.addEventListener("keydown",e=>{if(dlg.hidden)return;if(e.key==="Escape")closeDlg();
  if(e.key==="Tab"){const f=[...dlg.querySelectorAll("button,input")].filter(el=>!el.disabled&&el.offsetParent);
    if(!f.length)return;const a=f[0],z=f[f.length-1];
    if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus();}
    else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus();}}});
})();
"""


def _finder(event: dict) -> tuple[str, str, str]:
    """'Encontrar minhas fotos': button, results bar and the consent + camera dialog."""
    ui = event.get("face_search_ui")
    if not ui:
        return "", "", ""
    contact = event.get("removal_contact", "")
    button = '<button class="btn primary find-me">Encontrar minhas fotos</button>'
    bar = ('<div class="found" hidden tabindex="-1"><h2></h2><button class="btn show-all">Ver todas as fotos</button>'
           '<p></p></div>')
    dialog = f"""<div class="finder" role="dialog" aria-modal="true" aria-labelledby="finder-title" hidden>
<div class="finder-box"><h2 id="finder-title">Encontrar minhas fotos</h2>
<div data-step="consent"><p>Tire uma selfie e mostramos só as fotos em que você aparece.</p>
<label class="consent"><input type="checkbox" id="consent"> Autorizo comparar minha selfie com os rostos das fotos deste evento. A selfie não é guardada.</label>
<p class="finder-small">Os rostos das fotos ficam guardados até {escape(ui["until"])} e depois são apagados.{f" Para sair da busca, escreva para {escape(contact)}." if contact else ""}</p>
<div class="finder-actions"><button class="btn finder-close">Cancelar</button><button class="btn primary open-cam" disabled>Abrir câmera</button></div></div>
<div data-step="camera" hidden><video playsinline muted aria-label="Câmera frontal"></video>
<div class="finder-actions"><button class="btn finder-close">Cancelar</button><button class="btn primary shoot">Tirar selfie</button></div></div>
<div data-step="busy" hidden><p class="finder-busy" role="status">Procurando suas fotos…</p></div>
<div data-step="message" hidden><p class="finder-message" role="alert"></p>
<div class="finder-actions"><button class="btn finder-close">Fechar</button><button class="btn primary retry">Tentar de novo</button></div></div>
</div></div>"""
    return button, bar, dialog


def _page(event: dict, photos: list[GalleryPhoto], designs: list[dict]) -> str:
    order = [m.title for m in event["moments"]] + [OTHER_MOMENT]
    groups = {title: [p for p in photos if p.moment == title] for title in order}
    groups = {k: v for k, v in groups.items() if v}
    starts = {m.title: m.start.strftime("%H:%M") for m in event["moments"]}
    alts = {p.id: _alt(p, i, len(photos)) for i, p in enumerate(photos, 1)}

    single = len(groups) == 1 and not event["moments"]
    chips = "".join(f'<a class="chip" href="#{_slug(t)}">{escape(t)} <span>{len(ps)}</span></a>'
                    for t, ps in groups.items())
    sections = []
    for title, items in groups.items():
        tiles = "".join(
            f'<a class="tile" href="#foto={escape(p.id)}" data-id="{escape(p.id)}">'
            f'<img src="thumbs/{escape(p.id)}.webp" width="{p.width}" height="{p.height}" loading="lazy" '
            f'alt="{escape(alts[p.id])}"></a>'
            for p in items)
        when = f'<span class="when">{starts[title]}</span>' if title in starts else ""
        heading = "" if single else f"<h2>{when}{escape(title)}</h2>"
        sections.append(f'<section id="{_slug(title)}">{heading}<div class="grid">{tiles}</div></section>')

    data = [{"id": p.id, "f": list(p.frames), "v": p.height > p.width, "a": alts[p.id], "c": p.by} for p in photos]
    nav = "" if single else f'<nav aria-label="Momentos do evento"><div class="chips">{chips}</div></nav>'
    authors = sorted({p.by for p in photos if p.by}) or ([event["photographer"]] if event.get("photographer") else [])
    credit = f"Fotos: {escape(', '.join(authors))}. " if authors else ""
    contact = event.get("removal_contact") or ""
    removal = (f'Não quer aparecer em alguma foto? Escreva para <a href="mailto:{escape(contact)}">{escape(contact)}</a> '
               "com o link da foto e ela será removida."
               if contact else "Não quer aparecer em alguma foto? Fale com a organização e ela será removida.")
    notice = f'<p>{escape(event["notice"])}</p>' if event.get("notice") else ""
    handle = escape(event.get("instagram", "").lstrip("@"))
    mention = (f'ao postar, marque <a href="https://www.instagram.com/{handle}/" rel="noopener">@{handle}</a>.'
               if handle else "ao postar, marque o evento.")
    find_button, found_bar, finder_dialog = _finder(event)
    finder_cfg = _script_json({"url": event["face_search_ui"]["url"], "ids": event["face_search_ui"]["ids"]}
                              if event.get("face_search_ui") else None)
    tag = (f'<p class="tag">Ao postar, marque <button class="copy-tag" data-tag="@{handle}" '
           f'aria-label="Copiar @{handle}">@{handle}</button></p>' if handle else "")
    banner = f'<p class="banner">{escape(event["banner"])}</p>' if event.get("banner") else ""
    credits = _credits(event.get("credits", []), [p.id for p in photos])
    accent = escape(event.get("accent", "#f28528"))
    # Each fact stays whole on narrow screens; only the separators may break.
    where = " · ".join(f'<span class="nw">{x}</span>' for x in (_date_pt(event["date"]), escape(event.get("place", ""))) if x)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="{BACKGROUND}">
<title>Fotos — {escape(event['name'])}</title>
<style>
:root{{--bg:{BACKGROUND};--panel:#161b22;--ink:#f0f3f6;--muted:#9aa4b2;--line:#2a313c;--accent:{accent};
  color-scheme:dark;accent-color:var(--accent);scrollbar-color:var(--line) var(--bg)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:64px}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}*{{transition:none!important}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-tap-highlight-color:transparent}}
::selection{{background:var(--accent);color:#111}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
header{{padding:40px 20px 20px;max-width:1400px;margin:0 auto}}
h1{{font-size:clamp(28px,6vw,48px);line-height:1.1;letter-spacing:-.01em;margin:0 0 10px;text-wrap:balance}}
.sub{{color:var(--muted);margin:0;text-wrap:pretty}}.nw{{white-space:nowrap}}.sub b{{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}}
nav{{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line)}}
.chips{{display:flex;gap:8px;overflow-x:auto;padding:10px 20px;max-width:1400px;margin:0 auto;scrollbar-width:none}}
.chip{{flex:none;color:var(--ink);text-decoration:none;border:1px solid var(--line);background:var(--panel);
  min-height:44px;display:inline-flex;align-items:center;padding:0 14px;border-radius:99px;font-size:14px;white-space:nowrap}}
.chip span{{color:var(--muted);margin-left:6px;font-variant-numeric:tabular-nums}}
.chip:hover{{border-color:var(--accent)}}
main{{max-width:1400px;margin:0 auto;padding:8px 12px 40px}}
h2{{font-size:20px;margin:32px 8px 12px;display:flex;align-items:baseline;gap:10px}}
.when{{color:var(--accent);font-size:15px;font-variant-numeric:tabular-nums}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:6px}}
@media(min-width:700px){{.grid{{grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px}}}}
.tile{{display:block;overflow:hidden;border-radius:8px;background:var(--panel);aspect-ratio:1/1}}
.tile img{{width:100%;height:100%;object-fit:cover;display:block;transition:transform .3s cubic-bezier(.16,1,.3,1)}}
.tile:hover img{{transform:scale(1.03)}}
footer{{color:var(--muted);font-size:14px;max-width:1400px;margin:0 auto;padding:24px 20px 48px;border-top:1px solid var(--line)}}
footer a{{color:var(--ink);text-underline-offset:3px}}
footer summary{{cursor:pointer;color:var(--ink);min-height:44px;display:flex;align-items:center}}
footer ol{{margin:8px 0 0;padding-left:20px;line-height:1.7}}
.banner{{display:inline-block;margin:0 0 14px;padding:6px 12px;border-radius:8px;font-size:14px;font-weight:600;
  color:var(--ink);background:color-mix(in srgb,var(--accent) 22%,transparent)}}
.to-top{{position:fixed;right:16px;bottom:calc(16px + env(safe-area-inset-bottom));z-index:6;width:48px;height:48px;
  border-radius:99px;border:0;background:var(--panel);color:var(--ink);display:grid;place-items:center;
  cursor:pointer;box-shadow:0 6px 20px #0008;opacity:0;transform:translateY(12px);pointer-events:none;
  transition:opacity .25s,transform .35s cubic-bezier(.16,1,.3,1)}}
.to-top.show{{opacity:1;transform:none;pointer-events:auto}}
.viewer{{position:fixed;inset:0;z-index:20;background:#000;display:none;flex-direction:column}}
.viewer.open{{display:flex}}
.top{{display:flex;align-items:center;justify-content:space-between;padding:calc(6px + env(safe-area-inset-top)) 8px 6px 16px}}
.count{{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}}
.icon-btn{{width:44px;height:44px;border:0;border-radius:99px;background:#ffffff14;color:#fff;display:grid;place-items:center;cursor:pointer}}
.icon-btn:hover{{background:#ffffff26}}
.stage{{flex:1;position:relative;display:flex;align-items:center;justify-content:center;min-height:0;touch-action:pan-y}}
.stage img{{max-width:100%;max-height:100%;object-fit:contain;user-select:none;transition:opacity .2s}}
.stage.loading img{{opacity:.35}}
.stage::after{{content:"";position:absolute;width:36px;height:36px;border-radius:50%;border:3px solid #ffffff33;
  border-top-color:#fff;opacity:0;transition:opacity .2s;animation:spin .8s linear infinite;pointer-events:none}}
.stage.loading::after{{opacity:1;transition-delay:.15s}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.stage .failed{{position:absolute;inset:auto 24px;text-align:center;color:var(--ink)}}
.nav-btn{{position:absolute;top:50%;transform:translateY(-50%);width:48px;height:64px;border-radius:10px;background:#0009}}
.prev{{left:8px}}.next{{right:8px}}
@media(hover:none){{.nav-btn{{display:none}}}}
.controls{{display:grid;gap:10px;padding:10px 12px calc(12px + env(safe-area-inset-bottom));
  max-width:560px;width:100%;margin:0 auto}}
.modes{{display:grid;grid-template-columns:repeat(var(--n,2),1fr);padding:4px;border-radius:12px;background:#1a1a1a}}
.modes.many{{gap:4px}}
.modes.many button{{display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 2px;font-size:13px}}
.modes.many img,.modes .none{{width:40px;height:50px;border-radius:4px;object-fit:cover}}
.modes .none{{display:block;background:linear-gradient(160deg,#b8a9d6,#6f5a9a)}}
.modes button{{min-height:40px;border:0;border-radius:9px;background:none;color:#cfd4da;font:500 15px system-ui,sans-serif;cursor:pointer}}
.modes button[aria-pressed=true]{{background:var(--ink);color:#111;font-weight:600}}
.actions{{display:flex;gap:8px}}
.btn{{flex:1;min-height:48px;border:0;border-radius:12px;padding:0 16px;font:600 16px system-ui,sans-serif;cursor:pointer;
  background:#262626;color:#fff;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}}
.btn.primary{{background:var(--accent);color:#111}}
.btn:disabled{{opacity:.6;cursor:progress}}
.btn[hidden],.modes[hidden]{{display:none}}
.tag{{margin:0;text-align:center;font-size:14px;color:#cfd4da}}
.copy-tag{{min-height:44px;padding:0 6px;border:0;background:none;color:var(--accent);font:600 14px system-ui,sans-serif;
  text-decoration:underline;text-underline-offset:3px;cursor:pointer}}
.toast{{position:fixed;left:50%;bottom:calc(210px + env(safe-area-inset-bottom));transform:translate(-50%,8px);z-index:30;
  width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:#111;padding:10px 16px;border-radius:10px;font-size:15px;
  box-shadow:0 8px 24px #000a;opacity:0;pointer-events:none;transition:opacity .2s,transform .3s cubic-bezier(.16,1,.3,1)}}
.toast.show{{opacity:1;transform:translate(-50%,0)}}{FINDER_CSS if find_button else ""}
</style></head>
<body>
<header>{banner}<h1>{escape(event['name'])}</h1>
<p class="sub">{where}</p>
<p class="sub"><b>{len(photos)} fotos</b> do evento. Toque numa foto para ver, salvar ou postar.</p>{find_button}</header>
{nav}{found_bar}
<main>{''.join(sections)}</main>
<footer><p>{credit}Uso pessoal liberado; {mention}</p>
<p>{removal}</p>{notice}{credits}</footer>
<button class="to-top" aria-label="Voltar ao topo">{_icon("up")}</button>
<div class="viewer" role="dialog" aria-modal="true" aria-label="Foto ampliada">
  <div class="top"><span class="count" aria-live="polite"></span>
    <button class="icon-btn close" aria-label="Fechar">{_icon("close")}</button></div>
  <div class="stage"><img alt=""><p class="failed" hidden>Não foi possível carregar a foto. Verifique a conexão e tente de novo.</p>
    <button class="icon-btn nav-btn prev" aria-label="Foto anterior">{_icon("prev")}</button>
    <button class="icon-btn nav-btn next" aria-label="Próxima foto">{_icon("next")}</button></div>
  <div class="controls">
    {_modes(designs)}
    <div class="actions"><button class="btn primary share" hidden>Salvar ou postar</button><a class="btn download" download>Baixar arquivo</a></div>
    {tag}
  </div>
</div>
{finder_dialog}
<div class="toast" role="status" aria-live="polite"></div>
<script>
const PHOTOS={_script_json(data, separators=(",", ":"))},FINDER={finder_cfg};
let VIEW=PHOTOS; /* the photos the viewer walks through: all of them, or the face search result */
const viewer=document.querySelector(".viewer"),stage=viewer.querySelector(".stage"),img=stage.querySelector("img"),
  failed=stage.querySelector(".failed"),count=viewer.querySelector(".count"),dl=viewer.querySelector(".download"),
  share=viewer.querySelector(".share"),modesBox=viewer.querySelector(".modes"),toast=document.querySelector(".toast"),
  toTop=document.querySelector(".to-top"),behind=[...document.querySelectorAll("header,nav,main,footer,.to-top,.found")];
const modes=[...modesBox.querySelectorAll("button")];
let index=-1,lastFocus=null,mode=modes[0].dataset.mode,busy=false,toastTimer=0;
/* Feed or story follows the photo: vertical photos are what people post as stories. */
function frameOf(p){{if(!p.f.length)return null;const pref=p.v?"story":"feed";return p.f.includes(pref)?pref:p.f[0];}}
function current(p){{const f=mode!=="photo"?frameOf(p):null,u=f+"/"+mode+"/"+p.id+".jpg";
  return f?{{src:u,file:u,name:p.id+"-"+mode+"-"+f+".jpg"}}
  :{{src:"view/"+p.id+".webp",file:"photos/"+p.id+".jpg",name:p.id+".jpg"}};}}
function say(text){{toast.textContent=text;toast.classList.add("show");clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>toast.classList.remove("show"),3500);}}
function show(i){{
  index=(i+VIEW.length)%VIEW.length;const p=VIEW[index],c=current(p);
  modesBox.hidden=!p.f.length;modes.forEach(b=>b.setAttribute("aria-pressed",b.dataset.mode===(p.f.length?mode:"photo")));
  failed.hidden=true;stage.classList.add("loading");img.alt=p.a;img.src=c.src;
  if(img.complete&&img.naturalWidth)stage.classList.remove("loading");
  dl.href=c.file;dl.setAttribute("download",c.name);
  count.textContent=(index+1)+" de "+VIEW.length+(p.c?" · Foto: "+p.c:"");
  const next=VIEW[(index+1)%VIEW.length];new Image().src=current(next).src;
  history.replaceState({{viewer:1}},"","#foto="+p.id);
}}
img.onload=()=>stage.classList.remove("loading");
img.onerror=()=>{{stage.classList.remove("loading");failed.hidden=false;}};
function open(id,push){{lastFocus=document.activeElement;
  if(push)history.pushState({{viewer:1}},"","#foto="+id);
  viewer.classList.add("open");document.body.style.overflow="hidden";behind.forEach(e=>e.inert=true);
  if(!VIEW.some(p=>p.id===id))VIEW=PHOTOS;show(Math.max(0,VIEW.findIndex(p=>p.id===id)));viewer.querySelector(".close").focus();}}
function hide(){{viewer.classList.remove("open");document.body.style.overflow="";behind.forEach(e=>e.inert=false);
  lastFocus&&lastFocus.focus();}}
/* Opening a photo adds a history step, so the phone's back gesture closes it instead of leaving the gallery. */
function close(){{if(history.state&&history.state.viewer)history.back();else{{hide();history.replaceState(null,"",location.pathname);}}}}
addEventListener("popstate",()=>{{const m=location.hash.match(/^#foto=(.+)$/);
  if(m&&!viewer.classList.contains("open"))open(decodeURIComponent(m[1]),false);
  else if(!m&&viewer.classList.contains("open"))hide();}});
document.querySelectorAll(".tile").forEach(t=>t.addEventListener("click",e=>{{e.preventDefault();open(t.dataset.id,true);}}));
viewer.querySelector(".prev").onclick=()=>show(index-1);viewer.querySelector(".next").onclick=()=>show(index+1);
viewer.querySelector(".close").onclick=close;
modes.forEach(b=>b.onclick=()=>{{mode=b.dataset.mode;show(index);}});
document.addEventListener("keydown",e=>{{if(!viewer.classList.contains("open"))return;
  if(e.key==="Escape")close();if(e.key==="ArrowLeft")show(index-1);if(e.key==="ArrowRight")show(index+1);
  if(e.key==="Tab"){{const f=[...viewer.querySelectorAll("button,a[href]")].filter(el=>!el.hidden&&el.offsetParent);
    if(!f.length)return;const first=f[0],last=f[f.length-1];
    if(e.shiftKey&&document.activeElement===first){{e.preventDefault();last.focus();}}
    else if(!e.shiftKey&&document.activeElement===last){{e.preventDefault();first.focus();}}}}}});
let x0=null;
stage.addEventListener("touchstart",e=>x0=e.touches[0].clientX,{{passive:true}});
stage.addEventListener("touchend",e=>{{if(x0===null)return;const dx=e.changedTouches[0].clientX-x0;
  if(Math.abs(dx)>50)show(index+(dx<0?1:-1));x0=null;}});
/* Where files can be shared (phones), the share sheet is how a photo reaches the camera roll ("Salvar imagem"). */
const probe=new File([""],"x.jpg",{{type:"image/jpeg"}});
if(navigator.canShare&&navigator.canShare({{files:[probe]}})){{share.hidden=false;share.onclick=async()=>{{
  if(busy)return;busy=true;share.disabled=true;share.textContent="Preparando…";
  const p=VIEW[index],c=current(p);
  try{{const res=await fetch(c.file);if(!res.ok)throw new Error(res.status);
    await navigator.share({{files:[new File([await res.blob()],c.name,{{type:"image/jpeg"}})]}});}}
  catch(e){{if(e.name!=="AbortError")say("Não deu para abrir o compartilhamento. Tente “Baixar arquivo”.");}}
  finally{{busy=false;share.disabled=false;share.textContent="Salvar ou postar";}}}};}}
else{{dl.classList.add("primary");dl.textContent="Baixar foto";}}
const copyTag=document.querySelector(".copy-tag");
if(copyTag)copyTag.onclick=async()=>{{try{{await navigator.clipboard.writeText(copyTag.dataset.tag);
  say(copyTag.dataset.tag+" copiado. Cole na legenda ao postar.");}}catch(e){{say("Marque "+copyTag.dataset.tag+" ao postar.");}}}};
toTop.onclick=()=>scrollTo({{top:0}});
addEventListener("scroll",()=>toTop.classList.toggle("show",scrollY>innerHeight*1.5),{{passive:true}});
const m=location.hash.match(/^#foto=(.+)$/);
if(m){{history.replaceState(null,"",location.pathname);open(decodeURIComponent(m[1]),true);}}
{FINDER_JS if find_button else ""}
</script>
</body></html>"""
