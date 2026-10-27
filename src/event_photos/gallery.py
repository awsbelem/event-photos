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

from . import brand
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
    sample = f'<img src="data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode()}" alt="" width="{im.width}" height="{im.height}">'
    # The swatch is the feed format; the open photo is drawn into the frame's photo box (set by the viewer script).
    config = json.loads((FRAMES_DIR / key / "frame.json").read_text()) if (FRAMES_DIR / key / "frame.json").exists() else {}
    box = config.get("formats", {}).get("feed", {}).get("box")
    if not box:
        return sample
    x0, y0, x1, y1 = box
    window = f"--x:{x0 / 10.8:.2f}%;--y:{y0 / 13.5:.2f}%;--w:{(x1 - x0) / 10.8:.2f}%;--h:{(y1 - y0) / 13.5:.2f}%"
    return f'<span class="sw" style="{window}">{sample}<span class="ph"></span></span>'


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


FORMAT_LABELS = {"feed": "Post (4:5)", "story": "Story (9:16)"}


def _formats(designs: list[dict]) -> str:
    """Post or story for a framed photo; the viewer presses the one that fits the photo until the visitor picks."""
    if not designs:
        return ""
    buttons = "".join(f'<button data-format="{f}" aria-pressed="false">{FORMAT_LABELS[f]}</button>'
                      for f in FRAME_FORMATS)
    return f'<div class="modes formats" role="group" aria-label="Formato" style="--n:{len(FRAME_FORMATS)}">{buttons}</div>'


TILE_BATCH = 60  # divides by every column count the grid uses (2 to 6), so batches end on a full row

# Tiles are added a batch at a time as the visitor scrolls: a gallery of thousands of photos keeps a few hundred
# elements on the page. The space of the tiles not built yet is reserved (tiles are square), so the scrollbar and
# the schedule links land where the photos will be. Built with DOM calls, never innerHTML: alts carry names.
TILES_JS = """
const SECTIONS=[...document.querySelectorAll("main section")].map(el=>({el,grid:el.querySelector(".grid"),
  rest:el.querySelector(".rest"),link:document.querySelector('.sched a[href="#'+el.id+'"]'),
  count:el.querySelector(".n"),items:[],done:0}));
let queued=false;
function tile(p){const a=document.createElement("a"),im=document.createElement("img");
  a.className="tile";a.href="#foto="+encodeURIComponent(p.id);a.dataset.id=p.id;
  im.src="thumbs/"+p.id+".webp";im.width=p.w;im.height=p.h;im.loading="lazy";im.decoding="async";im.alt=p.a;
  a.append(im);return a;}
function reserve(s){const cs=getComputedStyle(s.grid),cols=cs.gridTemplateColumns.split(" ").length||1,
  size=parseFloat(cs.gridTemplateColumns)||0,gap=parseFloat(cs.rowGap)||0,
  rows=Math.ceil(s.items.length/cols)-Math.ceil(s.done/cols);
  s.rest.style.height=rows>0?rows*(size+gap)+"px":"0";}
/* Only while the reserved space reaches into the screen (or starts just below it). A section ending at the top of the
   screen, under the sticky moment bar after a jump, waits until the visitor scrolls back up to it. */
function near(s){const r=s.rest.getBoundingClientRect();return r.top<innerHeight*3&&r.bottom>innerHeight/4;}
/* At most `budget` tiles per frame, so a jump deep into a long section does not freeze the phone. */
function fill(s,budget){while(budget>0&&s.done<s.items.length&&near(s)){const f=document.createDocumentFragment();
  s.items.slice(s.done,s.done+BATCH).forEach(p=>f.append(tile(p)));s.grid.append(f);
  s.done=Math.min(s.items.length,s.done+BATCH);budget-=BATCH;reserve(s);}return budget;}
function tick(){queued=false;let budget=BATCH*6;for(const s of SECTIONS)if(!s.el.hidden)budget=fill(s,budget);
  if(budget<=0)queue();}
function queue(){if(!queued){queued=true;requestAnimationFrame(tick);}}
/* Shows `list` (all photos, or the face search result) in its sections, from the first tile again. */
function layout(list){SECTIONS.forEach((s,i)=>{s.items=list.filter(p=>p.m===i);s.done=0;s.grid.replaceChildren();
  const n=s.items.length;s.el.hidden=!n&&list!==PHOTOS;s.el.classList.toggle("empty",!n);
  if(s.link){s.link.parentElement.hidden=s.el.hidden;s.link.querySelector(".c").textContent=n||"";}
  if(s.count){s.count.textContent=n+(n===1?" foto":" fotos");s.count.hidden=!n;}reserve(s);});queue();if(window.now)window.now();}
addEventListener("scroll",queue,{passive:true});
addEventListener("resize",()=>{SECTIONS.forEach(reserve);queue();});
layout(PHOTOS);
""".replace("BATCH", str(TILE_BATCH))

FINDER_CSS = """
.find-me{display:flex;margin-top:22px;width:100%;max-width:360px}
.tile[hidden],section[hidden],.sched li[hidden],.found[hidden],.finder[hidden],[data-step][hidden]{display:none}
.found{max-width:1200px;margin:20px auto 0;padding:16px 20px;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.found h2{margin:0;font-size:22px;font-weight:800;letter-spacing:-.02em}.found p{margin:0;color:var(--muted);flex-basis:100%}
.found p:empty{display:none}.found:focus{outline:none}.found .btn{flex:none;min-height:44px}
.finder{position:fixed;inset:0;z-index:40;background:#06111fd9;display:grid;place-items:center;padding:16px}
.finder-box{width:100%;max-width:460px;background:var(--raised);border-radius:16px;padding:22px;
  box-shadow:0 24px 64px #0009}
.finder-box h2{margin:0 0 12px;font-size:24px;font-weight:800;letter-spacing:-.02em}
.finder-box p{color:var(--muted);margin:0 0 14px}
.consent{display:flex;gap:12px;align-items:flex-start;padding:14px;border:1px solid var(--rule);border-radius:12px;
  color:var(--ink);margin-bottom:12px;cursor:pointer;background:var(--navy)}
.consent:has(input:checked){border-color:var(--orange)}
.consent input{width:22px;height:22px;flex:none;margin-top:1px}
.finder-small{font-size:13px}
.finder-actions{display:flex;gap:8px;margin-top:8px}
.finder video{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:12px;background:#000;transform:scaleX(-1)}
.finder-busy{font-size:17px;color:var(--ink)!important;padding:28px 0;text-align:center}
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
function filter(ids,note){VIEW=PHOTOS.filter(p=>ids.has(p.id));layout(VIEW);
  bar.querySelector("h2").textContent="Encontramos "+VIEW.length+(VIEW.length===1?" foto com você":" fotos com você");
  bar.querySelector("p").textContent=note||"";bar.hidden=false;bar.focus();}
bar.querySelector(".show-all").onclick=()=>{VIEW=PHOTOS;layout(PHOTOS);bar.hidden=true;btn.focus();};
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


PAGE_CSS = """
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:72px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before{transition:none!important;animation:none!important}}
body{margin:0;background:var(--navy);color:var(--ink);font:16px/1.5 FONT;-webkit-tap-highlight-color:transparent;
  -webkit-font-smoothing:antialiased}
::selection{background:var(--orange);color:var(--navy)}
:focus-visible{outline:2px solid var(--orange);outline-offset:3px;border-radius:4px}
a{color:var(--ink);text-decoration-color:var(--orange);text-underline-offset:3px}
.masthead{position:relative;padding:calc(30px + env(safe-area-inset-top)) 20px 8px;overflow:hidden}
.hex{position:absolute;top:0;height:auto;pointer-events:none;user-select:none}
.hex-l{left:0;width:clamp(28px,7.8vw,84px)}.hex-r{right:0;width:clamp(60px,16.7vw,180px)}
.logo{display:block;width:clamp(230px,62vw,340px);height:auto;margin:0 auto 44px}
.intro{max-width:1200px;margin:0 auto}
h1{font-weight:800;font-size:clamp(42px,11.5vw,84px);line-height:.98;letter-spacing:-.04em;margin:0 0 16px;text-wrap:balance}
.sub{color:var(--muted);margin:0;font-size:17px;text-wrap:pretty}.nw{white-space:nowrap}
.sub b{color:var(--ink);font-weight:700;font-variant-numeric:tabular-nums}
.banner{display:block;width:fit-content;margin:18px 0 0;padding:7px 14px;border-radius:10px;font-size:14px;font-weight:700;
  color:#fff;background:var(--violet)}
.now{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--navy) 90%,transparent);
  -webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-bottom:1px solid var(--rule)}
.now details{max-width:1200px;margin:0 auto}
.now summary{list-style:none;display:flex;align-items:center;gap:10px;min-height:60px;padding:0 20px;cursor:pointer}
.now summary::-webkit-details-marker{display:none}
.now summary .node{flex:none}.now.before summary .node,.now.before .t{display:none}.now.before .nm{color:var(--muted);font-weight:600}
.now .t{color:var(--orange);font-weight:800;font-size:19px;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.now .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700}
.now .all{flex:none;display:inline-flex;align-items:center;gap:2px;color:var(--muted);font-size:14px;font-weight:600}
.now .all svg{transition:transform .3s cubic-bezier(.16,1,.3,1)}.now details[open] .all svg{transform:rotate(180deg)}
.sched{position:absolute;left:0;right:0;top:100%;margin:0;padding:8px 12px 16px;list-style:none;background:var(--navy);
  max-height:min(72vh,600px);overflow:auto;box-shadow:0 24px 48px #0008}
.sched ol{list-style:none;margin:0 auto;padding:0;max-width:1176px}
.sched a{display:grid;grid-template-columns:62px 22px 1fr auto;align-items:center;gap:12px;min-height:52px;padding:0 8px;
  border-radius:10px;color:var(--ink);text-decoration:none}
.sched a:hover{background:var(--raised)}
.sched a[aria-current=true]{background:var(--raised)}
.sched .st{color:var(--orange);font-weight:800;font-variant-numeric:tabular-nums}
.sched .sn{font-weight:600;min-width:0}
.sched .c{color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
.node path{fill:var(--navy);stroke:var(--orange);stroke-width:2.4;stroke-linejoin:round;
  transition:fill .45s cubic-bezier(.16,1,.3,1),stroke .45s}
.keynote .node path,.node.key path{fill:var(--lavender);stroke:var(--lavender)}
main{max-width:1200px;margin:0 auto;padding:36px 20px 24px}
.moment{position:relative;display:grid;grid-template-columns:28px 1fr;grid-template-areas:"node time" ". body";
  column-gap:12px;padding-bottom:40px}
.moment::before{content:"";position:absolute;left:13px;top:18px;bottom:-18px;width:2px;background:var(--rule)}
.moment:last-of-type::before{display:none}
.stamp{display:contents}
.stamp time{grid-area:time;align-self:center;color:var(--orange);font-weight:800;font-size:34px;line-height:1;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.moment>.stamp .node{grid-area:node;align-self:center;position:relative;width:28px;height:28px}
.moment>.stamp .node path{transform-origin:12px 12px;transition:fill .45s cubic-bezier(.16,1,.3,1),stroke .45s,
  transform .6s cubic-bezier(.16,1,.3,1)}
.moment.lit>.stamp .node path{fill:var(--orange);stroke:var(--orange)}
.moment.keynote.lit>.stamp .node path{fill:var(--lavender);stroke:var(--orange)}
.moment.lit.pop>.stamp .node path{transform:scale(1.18)}
.body{grid-area:body;min-width:0}
h2{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:6px 0 16px;font-size:22px;font-weight:700;
  line-height:1.25;letter-spacing:-.015em;text-wrap:balance}
.n{display:inline-block;padding:3px 9px;border-radius:7px;background:var(--violet);color:#fff;font-size:12px;font-weight:700;
  letter-spacing:.04em;text-transform:uppercase;font-variant-numeric:tabular-nums}
.moment.empty{padding-bottom:30px}.moment.empty h2{margin-bottom:0}.n[hidden]{display:none}
.moment.empty .stamp time{color:color-mix(in srgb,var(--orange) 70%,var(--navy))}
.moment.lit::before{background:var(--orange)}.moment::before{transition:background-color .6s cubic-bezier(.16,1,.3,1)}
.moment.plain{display:block;padding-bottom:24px}.moment.plain::before{display:none}
@media(min-width:860px){
  .moment{grid-template-columns:132px 32px 1fr;grid-template-areas:"time node body";column-gap:18px;padding-bottom:56px}
  .moment::before{left:165px;top:22px;bottom:-22px}
  .stamp time{align-self:start;justify-self:start;font-size:44px;line-height:44px}
  .intro{padding:0 20px}
  .moment>.stamp .node{align-self:start;width:32px;height:44px}
  h2{min-height:44px;margin-top:0;font-size:26px}
  .masthead{padding-top:40px}.logo{margin-bottom:56px}}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px}
@media(min-width:700px){.grid{grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px}}
.rest{overflow-anchor:none} /* the browser keeps the screen still by the tiles, not by the space they will fill */
.tile{display:block;overflow:hidden;border-radius:8px;background:var(--raised);aspect-ratio:1/1}
.tile img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .35s cubic-bezier(.16,1,.3,1)}
.tile:hover img{transform:scale(1.04)}
footer{max-width:1200px;margin:0 auto;padding:28px 20px 0;color:var(--muted);font-size:15px;border-top:1px solid var(--rule)}
footer p{margin:0 0 10px;max-width:68ch}
footer summary{cursor:pointer;color:var(--ink);min-height:44px;display:flex;align-items:center;font-weight:600}
footer ol{margin:8px 0 0;padding-left:20px;line-height:1.7}
.skyline{display:block;width:calc(100% + 40px);max-width:1080px;height:auto;margin:28px -20px 0;user-select:none}
@media(min-width:1120px){.skyline{margin:36px auto 0;width:100%;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent);mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent)}}
.btn{flex:1;min-height:52px;border:0;border-radius:12px;padding:0 18px;font:700 16px/1 FONT;cursor:pointer;
  background:var(--raised);color:var(--ink);text-decoration:none;display:inline-flex;align-items:center;justify-content:center;
  gap:8px;transition:background .2s,transform .2s cubic-bezier(.16,1,.3,1)}
.btn:hover{background:#1a3460}.btn:active{transform:scale(.98)}
.btn.primary{background:var(--orange);color:var(--navy)}.btn.primary:hover{background:#ff9a3d}
.btn:disabled{opacity:.55;cursor:not-allowed}.btn:disabled:active{transform:none}
.btn[hidden],.modes[hidden]{display:none}
.to-top{position:fixed;right:16px;bottom:calc(16px + env(safe-area-inset-bottom));z-index:6;width:52px;height:52px;
  border-radius:14px;border:0;background:var(--raised);color:var(--orange);display:grid;place-items:center;
  cursor:pointer;box-shadow:0 8px 24px #0009;opacity:0;transform:translateY(12px);pointer-events:none;
  transition:opacity .25s,transform .35s cubic-bezier(.16,1,.3,1)}
.to-top.show{opacity:1;transform:none;pointer-events:auto}
.viewer{position:fixed;inset:0;z-index:20;background:var(--deep);display:none;flex-direction:column}
.viewer.open{display:flex}
.top{display:flex;align-items:center;gap:12px;padding:calc(8px + env(safe-area-inset-top)) 8px 8px 16px}
.where{flex:1;min-width:0;display:grid;line-height:1.3}
.vm{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.vm b{color:var(--orange);font-weight:800;
  font-variant-numeric:tabular-nums;margin-right:6px}
.count{color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.icon-btn{flex:none;width:48px;height:48px;border:0;border-radius:14px;background:#ffffff14;color:#fff;display:grid;
  place-items:center;cursor:pointer}
.icon-btn:hover{background:#ffffff26}
.stage{flex:1;position:relative;display:flex;align-items:center;justify-content:center;min-height:0;touch-action:pan-y}
.stage img{max-width:100%;max-height:100%;object-fit:contain;user-select:none;transition:opacity .2s}
.stage.loading img{opacity:.35}
.stage::after{content:"";position:absolute;width:36px;height:36px;border-radius:50%;border:3px solid #ffffff33;
  border-top-color:var(--orange);opacity:0;transition:opacity .2s;animation:spin .8s linear infinite;pointer-events:none}
.stage.loading::after{opacity:1;transition-delay:.15s}
@keyframes spin{to{transform:rotate(360deg)}}
.stage .failed{position:absolute;inset:auto 24px;text-align:center;color:var(--ink)}
.nav-btn{position:absolute;top:50%;transform:translateY(-50%);width:52px;height:68px;border-radius:14px;background:#06111fb3}
.prev{left:8px}.next{right:8px}
@media(hover:none){.nav-btn{display:none}}
.controls{display:grid;gap:12px;padding:12px 12px calc(14px + env(safe-area-inset-bottom));max-width:560px;width:100%;margin:0 auto}
.modes{display:grid;grid-template-columns:repeat(var(--n,2),1fr);padding:4px;border-radius:14px;background:var(--raised)}
.modes.many{gap:4px}
.modes.many button{display:flex;flex-direction:column;align-items:center;gap:5px;padding:7px 2px;font-size:13px}
.modes.many img,.modes .none{width:40px;height:50px;border-radius:5px;object-fit:cover}
.modes .none{display:block;background:var(--raised) center/cover}
.modes .sw{position:relative;display:block;width:40px;height:50px}.modes .sw img{display:block}
.modes .ph{position:absolute;left:var(--x);top:var(--y);width:var(--w);height:var(--h);background:center/cover}
.modes button{min-height:44px;border:0;border-radius:10px;background:none;color:var(--muted);font:600 15px FONT;cursor:pointer}
.modes button[aria-pressed=true]{background:var(--ink);color:var(--navy);font-weight:700}
.actions{display:flex;gap:8px}
.tag{margin:0;text-align:center;font-size:14px;color:var(--muted)}
.copy-tag{min-height:44px;padding:0 6px;border:0;background:none;color:var(--orange);font:700 14px FONT;
  text-decoration:underline;text-underline-offset:3px;cursor:pointer}
.toast{position:fixed;left:50%;bottom:calc(220px + env(safe-area-inset-bottom));transform:translate(-50%,8px);z-index:30;
  width:max-content;max-width:calc(100% - 32px);background:var(--ink);color:var(--navy);padding:11px 16px;border-radius:12px;
  font-size:15px;font-weight:600;box-shadow:0 8px 24px #000a;opacity:0;pointer-events:none;
  transition:opacity .2s,transform .3s cubic-bezier(.16,1,.3,1)}
.toast.show{opacity:1;transform:translate(-50%,0)}
.modes.formats button{font-size:14px}
/* A phone on its side: stacked, the controls left the photo 87 px of a 390 px screen. The photo takes the full
   height on the left; the controls become a column on the right that scrolls if it does not fit. */
@media (orientation:landscape) and (max-height:540px){
  .viewer.open{display:grid;grid-template-columns:minmax(0,1fr) min(320px,42vw);grid-template-rows:auto minmax(0,1fr)}
  .stage{grid-column:1;grid-row:1/3;padding-left:env(safe-area-inset-left)}
  .top{grid-column:2;grid-row:1;padding:calc(8px + env(safe-area-inset-top)) calc(8px + env(safe-area-inset-right)) 4px 12px}
  .controls{grid-column:2;grid-row:2;align-content:start;overflow-y:auto;max-width:none;margin:0;
    padding:4px calc(12px + env(safe-area-inset-right)) calc(12px + env(safe-area-inset-bottom)) 12px}
  .toast{left:auto;right:calc(min(320px,42vw) / 2);max-width:calc(min(320px,42vw) - 24px);
    bottom:calc(16px + env(safe-area-inset-bottom));transform:translate(50%,8px)}
  .toast.show{transform:translate(50%,0)}
}
""".replace("FONT", brand.FONT_STACK)

# The sticky bar names the moment on screen and lights every node already reached: the day fills in as it is scrolled.
NOW_JS = """
const nowBox=document.querySelector(".now");
if(nowBox){const sum=nowBox.querySelector("details"),nowT=nowBox.querySelector(".t"),nowN=nowBox.querySelector(".nm"),
  links=[...nowBox.querySelectorAll(".sched a")];let cur,queuedNow=false;
  links.forEach(a=>a.addEventListener("click",()=>{sum.open=false;}));
  document.addEventListener("click",e=>{if(sum.open&&!nowBox.contains(e.target))sum.open=false;});
  document.addEventListener("keydown",e=>{if(e.key==="Escape"&&sum.open){sum.open=false;sum.querySelector("summary").focus();}});
  function measureNow(){queuedNow=false;const line=nowBox.getBoundingClientRect().bottom+32;let here=null;
    for(const s of SECTIONS){if(s.el.hidden)continue;const r=s.el.getBoundingClientRect();
      const lit=r.top<innerHeight*.6;if(lit&&!s.el.classList.contains("lit")){s.el.classList.add("lit","pop");
        setTimeout(()=>s.el.classList.remove("pop"),380);}else if(!lit)s.el.classList.remove("lit");
      if(r.top<=line)here=s;}
    if(here===cur)return;cur=here;nowBox.classList.toggle("before",!here);
    nowT.textContent=here?here.el.dataset.t||"":"";nowN.textContent=here?here.el.dataset.n:"Ir para um momento";
    links.forEach(a=>a.setAttribute("aria-current",String(!!here&&a.getAttribute("href")==="#"+here.el.id)));}
  window.now=()=>{if(!queuedNow){queuedNow=true;requestAnimationFrame(measureNow);}};
  addEventListener("scroll",window.now,{passive:true});addEventListener("resize",window.now);window.now();}
"""


def _section(title: str, start: str, count: int, single: bool) -> str:
    """One moment of the day: its time and hexagon on the timeline, then its photos (built by TILES_JS)."""
    tiles = '<div class="grid"></div><div class="rest"></div>'
    if single:
        return f'<section id="{_slug(title)}" class="moment plain"><div class="body">{tiles}</div></section>'
    kind = (" keynote" if title.lower().startswith("keynote") else "") + ("" if count else " empty")
    return (f'<section id="{_slug(title)}" class="moment{kind}" data-t="{start}" data-n="{escape(title)}">'
            f'<div class="stamp">{f"<time>{start}</time>" if start else "<span></span>"}{brand.hex_svg("node", 28)}</div>'
            f'<div class="body"><h2><span>{escape(title)}</span><span class="n"{"" if count else " hidden"}>{_count(count)}</span></h2>{tiles}</div></section>')


def _count(n: int) -> str:
    return f"{n} foto" if n == 1 else f"{n} fotos"


def _now_bar(groups: dict[str, list], starts: dict[str, str]) -> str:
    """Sticky 'where am I' bar; opening it lists the whole schedule to jump to a moment."""
    items = "".join(
        f'<li><a href="#{_slug(t)}" aria-current="false"><span class="st">{starts.get(t, "")}</span>'
        f'{brand.hex_svg("node" + (" key" if t.lower().startswith("keynote") else ""), 20)}'
        f'<span class="sn">{escape(t)}</span><span class="c">{len(ps) or ""}</span></a></li>'
        for t, ps in groups.items())
    chevron = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')
    return (f'<nav class="now before" aria-label="Momentos do dia"><details><summary>{brand.hex_svg("node", 22)}'
            '<span class="t"></span><span class="nm">Ir para um momento</span>'
            f'<span class="all">Programação{chevron}</span></summary>'
            f'<div class="sched"><ol>{items}</ol></div></details></nav>')


def _page(event: dict, photos: list[GalleryPhoto], designs: list[dict]) -> str:
    order = [m.title for m in event["moments"]] + [OTHER_MOMENT]
    groups = {title: [p for p in photos if p.moment == title] for title in order}
    groups = {k: v for k, v in groups.items() if v or k != OTHER_MOMENT}  # the whole schedule, with or without photos
    starts = {m.title: m.start.strftime("%H:%M") for m in event["moments"]}
    alts = {p.id: _alt(p, i, len(photos)) for i, p in enumerate(photos, 1)}
    art = brand.assets()

    single = len(groups) == 1 and not event["moments"]
    sections = [_section(t, starts.get(t, ""), len(ps), single) for t, ps in groups.items()]

    # Tiles are built by TILES_JS from this list ("m" = section), so the page stays small with thousands of photos.
    section_of = {title: i for i, title in enumerate(groups)}
    data = [{"id": p.id, "m": section_of[p.moment], "w": p.width, "h": p.height, "f": list(p.frames),
             "v": p.height > p.width, "a": alts[p.id], "c": p.by} for p in photos]
    moments = [{"t": starts.get(t, ""), "n": t} for t in groups]
    nav = "" if single else _now_bar(groups, starts)
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
    heading = escape(event.get("heading") or event["name"])
    # Each fact stays whole on narrow screens; only the separators may break.
    where = " · ".join(f'<span class="nw">{x}</span>' for x in (_date_pt(event["date"]), escape(event.get("place", ""))) if x)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="{brand.NAVY}">
<title>Fotos — {escape(event['name'])}</title>
<style>
{brand.font_face(art["font"])}
{brand.TOKENS}{PAGE_CSS}{FINDER_CSS if find_button else ""}
</style></head>
<body>
<header class="masthead"><img class="hex hex-l" src="{art["hex_left"]}" alt="" width="84" height="152">
<img class="hex hex-r" src="{art["hex_right"]}" alt="" width="180" height="164">
<img class="logo" src="{art["logo"]}" alt="{brand.LOGO_ALT}" width="353" height="141">
<div class="intro"><h1>{heading}</h1>
<p class="sub">{where}</p>
<p class="sub"><b>{_count(len(photos))}</b> do evento. Toque numa foto para ver, salvar ou postar.</p>{banner}{find_button}</div></header>
{nav}{found_bar}
<main>{''.join(sections)}<noscript><p>Ative o JavaScript do navegador para ver as fotos.</p></noscript></main>
<footer><p>{credit}Uso pessoal liberado; {mention}</p>
<p>{removal}</p>{notice}{credits}<img class="skyline" src="{art["skyline"]}" alt="" width="1080" height="250"></footer>
<button class="to-top" aria-label="Voltar ao topo">{_icon("up")}</button>
<div class="viewer" role="dialog" aria-modal="true" aria-label="Foto ampliada">
  <div class="top"><div class="where"><span class="vm"></span><span class="count" aria-live="polite"></span></div>
    <button class="icon-btn close" aria-label="Fechar">{_icon("close")}</button></div>
  <div class="stage"><img alt=""><p class="failed" hidden>Não foi possível carregar a foto. Verifique a conexão e tente de novo.</p>
    <button class="icon-btn nav-btn prev" aria-label="Foto anterior">{_icon("prev")}</button>
    <button class="icon-btn nav-btn next" aria-label="Próxima foto">{_icon("next")}</button></div>
  <div class="controls">
    {_modes(designs)}
    {_formats(designs)}
    <div class="actions"><button class="btn primary share" hidden>Salvar ou postar</button><a class="btn download" download>Baixar arquivo</a></div>
    {tag}
  </div>
</div>
{finder_dialog}
<div class="toast" role="status" aria-live="polite"></div>
<script>
const PHOTOS={_script_json(data, separators=(",", ":"))},FINDER={finder_cfg},MOMENTS={_script_json(moments, separators=(",", ":"))};
let VIEW=PHOTOS; /* the photos the viewer walks through: all of them, or the face search result */
const viewer=document.querySelector(".viewer"),stage=viewer.querySelector(".stage"),img=stage.querySelector("img"),
  failed=stage.querySelector(".failed"),count=viewer.querySelector(".count"),where=viewer.querySelector(".vm"),
  dl=viewer.querySelector(".download"),share=viewer.querySelector(".share"),modesBox=viewer.querySelector(".modes"),
  formatsBox=viewer.querySelector(".formats"),
  toast=document.querySelector(".toast"),toTop=document.querySelector(".to-top"),
  behind=[...document.querySelectorAll("header,nav,main,footer,.to-top,.found")];
const modes=[...modesBox.querySelectorAll("button")],formats=formatsBox?[...formatsBox.querySelectorAll("button")]:[];
let index=-1,lastFocus=null,mode=modes[0].dataset.mode,format=null,busy=false,toastTimer=0;
/* Post or story: the visitor's pick once there is one, else it follows the photo (vertical ones are what people
   post as stories). */
function frameOf(p){{if(!p.f.length)return null;const pref=format||(p.v?"story":"feed");
  return p.f.includes(pref)?pref:p.f[0];}}
function current(p){{const f=mode!=="photo"?frameOf(p):null,u=f+"/"+mode+"/"+p.id+".jpg";
  return f?{{src:u,file:u,name:p.id+"-"+mode+"-"+f+".jpg"}}
  :{{src:"view/"+p.id+".webp",file:"photos/"+p.id+".jpg",name:p.id+".jpg"}};}}
function say(text){{toast.textContent=text;toast.classList.add("show");clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>toast.classList.remove("show"),3500);}}
function show(i){{
  index=(i+VIEW.length)%VIEW.length;const p=VIEW[index],c=current(p),mo=MOMENTS[p.m];
  modesBox.hidden=!p.f.length;modes.forEach(b=>b.setAttribute("aria-pressed",b.dataset.mode===(p.f.length?mode:"photo")));
  if(formatsBox){{const f=frameOf(p);formatsBox.hidden=mode==="photo"||p.f.length<2;
    formats.forEach(b=>b.setAttribute("aria-pressed",b.dataset.format===f));}}
  failed.hidden=true;stage.classList.add("loading");img.alt=p.a;img.src=c.src;
  if(img.complete&&img.naturalWidth)stage.classList.remove("loading");
  dl.href=c.file;dl.setAttribute("download",c.name);
  const thumb="url("+JSON.stringify("thumbs/"+p.id+".webp")+")";
  modesBox.querySelectorAll(".ph,.none").forEach(e=>e.style.backgroundImage=thumb);
  const b=document.createElement("b");b.textContent=mo.t;where.replaceChildren(...(mo.t?[b]:[]),MOMENTS.length>1?mo.n:"");
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
{TILES_JS}
{NOW_JS}
document.querySelector("main").addEventListener("click",e=>{{const t=e.target.closest(".tile");
  if(t){{e.preventDefault();open(t.dataset.id,true);}}}});
viewer.querySelector(".prev").onclick=()=>show(index-1);viewer.querySelector(".next").onclick=()=>show(index+1);
viewer.querySelector(".close").onclick=close;
modes.forEach(b=>b.onclick=()=>{{mode=b.dataset.mode;show(index);}});
formats.forEach(b=>b.onclick=()=>{{format=b.dataset.format;show(index);}});
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
