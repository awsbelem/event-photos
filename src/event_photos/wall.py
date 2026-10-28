"""The venue screen (wall.html): the gallery's cover, live, on a TV or projector.

The official artwork frames one photo of the day at a time, with when and what it was and who shot it, and a QR
code to the gallery. It runs unattended: it reads the photo list published beside the gallery every minute and
shows new photos first. Page text is user-facing, so it is in Portuguese.
"""
from __future__ import annotations

from html import escape

from . import brand

WALL = "wall.html"
SECONDS = 8  # per photo; wall.html?s=12 changes it
REFRESH_MS = 60_000
HEARTBEAT_MS = 15 * 60_000  # one "wall" count every 15 min, so the report can tell how long it was on

# One unit is 1% of the largest 16:9 frame that fits the screen: the layout is pinned to the real screen edges, and
# only its scale follows 16:9, so 16:10 notebooks and 4:3 projectors get the artwork at their own corners.
CSS = """
:root{--u:min(1vh,.5625vw)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--navy);color:var(--ink);overflow:hidden}
body{font-family:FONT;-webkit-font-smoothing:antialiased;display:grid;place-items:center}
body.idle,body.idle *{cursor:none}
::selection{background:var(--orange);color:var(--navy)}
.wall{position:relative;width:100vw;height:100vh;overflow:hidden}
.hex{position:absolute;top:0;height:calc(var(--u)*15);width:auto;user-select:none;pointer-events:none}
.hex-l{left:0}.hex-r{right:0}
.top{position:absolute;left:0;right:0;top:calc(var(--u)*2.6);display:flex;flex-direction:column;align-items:center;
  gap:calc(var(--u)*1)}
.logo{height:calc(var(--u)*8.4);width:auto;display:block}
.banner{margin:0;background:var(--violet);color:var(--ink);font-weight:700;font-size:calc(var(--u)*1.7);
  padding:calc(var(--u)*.5) calc(var(--u)*1.1);border-radius:calc(var(--u)*.9)}
.stage{position:absolute;left:calc(var(--u)*22);right:calc(var(--u)*22);top:calc(var(--u)*14.5);
  bottom:calc(var(--u)*22);margin:0;border-radius:calc(var(--u)*1.2);overflow:hidden;background:var(--deep)}
.slide{position:absolute;inset:0;opacity:0;transition:opacity 1.2s cubic-bezier(.16,1,.3,1)}
.slide.on{opacity:1}
.slide .blur{position:absolute;inset:-8%;background-size:cover;background-position:center;
  filter:blur(calc(var(--u)*3)) brightness(.8)}
/* The photo's own colors, pulled toward the viewer's deep navy by a layer the blur's filter does not touch. */
.slide::after{content:"";position:absolute;inset:0;background:color-mix(in srgb,var(--deep) 70%,transparent)}
.slide img{position:absolute;inset:0;z-index:1;width:100%;height:100%;object-fit:contain}
.empty{position:absolute;inset:0;margin:0;display:grid;place-items:center;align-content:center;gap:calc(var(--u)*2.4);
  font-size:calc(var(--u)*4);font-weight:700;letter-spacing:-.015em;color:var(--muted)}
.empty .node{width:calc(var(--u)*7);height:calc(var(--u)*7)}
.empty[hidden],.when[hidden]{display:none}
.foot{position:absolute;left:0;right:0;bottom:0;height:calc(var(--u)*22)}
.skyline{position:absolute;left:50%;bottom:0;transform:translateX(-50%);height:calc(var(--u)*15);width:auto;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 18%,#000 82%,transparent);
  mask-image:linear-gradient(90deg,transparent,#000 18%,#000 82%,transparent);user-select:none;pointer-events:none}
/* Ends where the skyline's faded left side turns solid (64.8 units wide, centered, 18% faded), so the moment's
   title keeps its room and a long credit trails off instead of crossing the drawing. */
.when{position:absolute;left:calc(var(--u)*4.4);bottom:calc(var(--u)*2.2);
  max-width:calc(50vw - var(--u)*32.4 + var(--u)*11.7 - var(--u)*5.4);transition:opacity .4s}
.stamp{display:flex;align-items:center;gap:calc(var(--u)*1.6);margin-bottom:calc(var(--u)*.9)}
.when.out{opacity:0}
.time{color:var(--orange);font-weight:800;font-size:calc(var(--u)*8.2);line-height:1;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.when .node{flex:none;width:calc(var(--u)*4.6);height:calc(var(--u)*4.6)}
.when.untimed .time{display:none}
.moment{margin:0;font-size:calc(var(--u)*3.6);font-weight:700;line-height:1.15;letter-spacing:-.015em;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;text-wrap:balance}
/* The same "Nova" marker as the gallery's tiles, so a new photo looks new on both screens. */
.new{display:inline-block;vertical-align:.18em;margin-right:calc(var(--u)*1.1);background:var(--orange);
  color:var(--navy);font-size:calc(var(--u)*1.8);font-weight:800;line-height:1;padding:calc(var(--u)*.55) calc(var(--u)*.9);
  border-radius:calc(var(--u)*.7);letter-spacing:0}
.new[hidden]{display:none}
.by{margin:calc(var(--u)*.5) 0 0;color:var(--ink);font-size:calc(var(--u)*2.4);font-weight:600;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.node path{fill:var(--orange);stroke:var(--orange);stroke-width:2.4;stroke-linejoin:round;transform-origin:12px 12px;
  transition:transform .38s cubic-bezier(.16,1,.3,1)}
.empty .node path{fill:var(--navy)}
.when.key .node path{fill:var(--lavender);stroke:var(--lavender)}  /* keynotes, as on the agenda and the gallery */
.when.pop .node path{transform:scale(1.18)}
.invite{position:absolute;right:calc(var(--u)*4.4);bottom:calc(var(--u)*2.2);display:flex;align-items:center;
  gap:calc(var(--u)*2)}
.qr{width:calc(var(--u)*17.6);height:calc(var(--u)*17.6);background:#fff;border-radius:calc(var(--u)*1.2);
  overflow:hidden}
.qr svg{display:block;width:100%;height:100%}
.call{margin:0;font-size:calc(var(--u)*3.6);font-weight:800;letter-spacing:-.02em;line-height:1.1}
.how{margin:calc(var(--u)*.7) 0 0;color:var(--muted);font-size:calc(var(--u)*2.2);font-weight:600}
.address{margin:calc(var(--u)*1.2) 0 0;color:var(--ink);font-size:calc(var(--u)*2.2);font-weight:700;
  font-variant-numeric:tabular-nums}
.go{position:absolute;left:50%;bottom:calc(var(--u)*24);transform:translateX(-50%);z-index:2;min-height:52px;
  border:0;border-radius:12px;padding:0 22px;background:var(--orange);color:var(--navy);font:700 16px/1 FONT;
  cursor:pointer;box-shadow:0 8px 24px #0009;transition:opacity .3s}
.go:hover{background:#ff9a3d}.go:focus-visible{outline:2px solid var(--orange);outline-offset:3px}
body.idle .go,body.full .go{opacity:0;pointer-events:none}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

SCRIPT = r"""
const SECS=Math.max(4,Number(new URLSearchParams(location.search).get("s"))||SECONDS)*1000,
  stage=document.querySelector(".stage"),slides=[...stage.querySelectorAll(".slide")],empty=stage.querySelector(".empty"),
  when=document.querySelector(".when"),time=when.querySelector(".time"),nm=when.querySelector(".nm"),
  badge=when.querySelector(".new"),by=when.querySelector(".by"),go=document.querySelector(".go");
let photos=[],moments=[],known=null,arrivals=[],bag=[],current=null,front=0,timer=0;
slides.forEach(s=>s.append(document.createElement("img")));  /* each slide's photo, given its source as it comes up */
function hit(e){try{fetch("BEACON?e="+e+"&r="+Math.random().toString(36).slice(2,8),{keepalive:true,cache:"no-store"})
  .catch(()=>{});}catch(_){}}
/* New photos since the last reading go first; otherwise every photo once, in a shuffled round, before any repeats. */
async function load(){
  try{const r=await fetch("PHOTO_LIST",{cache:"no-cache"});if(!r.ok)throw new Error(r.status);const d=await r.json();
    if(known)d.photos.forEach(p=>{if(!known.has(p.id))arrivals.push(p.id);});
    known=new Set(d.photos.map(p=>p.id));photos=d.photos;moments=d.moments;}
  catch(e){}  /* no network: keep showing what we have */
}
function pick(){const ids=new Set(photos.map(p=>p.id));arrivals=arrivals.filter(id=>ids.has(id));
  if(arrivals.length)return {id:arrivals.shift(),fresh:true};
  bag=bag.filter(id=>ids.has(id));
  if(!bag.length){bag=[...ids].filter(id=>id!==current||ids.size===1);
    for(let i=bag.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[bag[i],bag[j]]=[bag[j],bag[i]];}}
  return bag.length?{id:bag.shift(),fresh:false}:null;}
function caption(p,fresh){const m=moments[p.m]||{t:"",n:""},t=p.t||m.t;
  time.textContent=t;when.classList.toggle("untimed",!t);when.classList.toggle("key",/^keynote/i.test(m.n));
  nm.textContent=m.n;badge.hidden=!fresh;
  by.textContent=p.c?"Foto: "+p.c:"";by.hidden=!p.c;}
async function step(){
  clearTimeout(timer);const next=pick();
  if(!next){empty.hidden=false;when.hidden=true;slides.forEach(s=>s.classList.remove("on"));timer=setTimeout(step,5000);return;}
  const p=photos.find(x=>x.id===next.id),slide=slides[front^1],img=slide.querySelector("img");
  img.src="view/"+p.id+".webp";img.alt=p.a||"";
  try{await img.decode();}catch(e){timer=setTimeout(step,500);return;}  /* a photo that will not load is skipped */
  slide.querySelector(".blur").style.backgroundImage="url("+JSON.stringify("thumbs/"+p.id+".webp")+")";
  empty.hidden=true;when.hidden=false;when.classList.add("out");
  setTimeout(()=>{caption(p,next.fresh);when.classList.remove("out");when.classList.add("pop");
    setTimeout(()=>when.classList.remove("pop"),380);},400);
  slide.classList.add("on");slides[front].classList.remove("on");front^=1;current=p.id;
  timer=setTimeout(step,SECS);}
/* Full screen and the cursor: the button only until the screen is running; both come back when the mouse moves. */
let idle=0;function awake(){document.body.classList.remove("idle");clearTimeout(idle);
  idle=setTimeout(()=>document.body.classList.add("idle"),3000);}
addEventListener("pointermove",awake);awake();
go.onclick=()=>{document.documentElement.requestFullscreen?.().catch(()=>{});};
document.addEventListener("fullscreenchange",()=>document.body.classList.toggle("full",!!document.fullscreenElement));
let lock=null;async function keepOn(){try{lock=await navigator.wakeLock?.request("screen");}catch(e){}}
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")keepOn();});
keepOn();
load().then(step);setInterval(load,REFRESH_MS);hit("wall");setInterval(()=>hit("wall"),HEARTBEAT_MS);
"""


def _qr(url: str) -> str:
    import segno

    # Low error correction keeps the modules big enough for a phone 3-5 m away; 4 modules of quiet zone, as the
    # standard asks, since the plate sits on a dark ground.
    return segno.make(url, error="l").svg_inline(dark=brand.NAVY, light="#ffffff", border=4, omitsize=True)


def page(event: dict, photo_list: str, beacon: str, icons: tuple[str, str]) -> str:
    art = brand.assets()
    # A short link (event.json "short_url") makes a sparser QR, readable from farther away, and is easier to type.
    url = event.get("short_url") or event.get("url") or ""
    address = url.split("://", 1)[-1].rstrip("/")  # what a visitor types: the host, without https://
    qr = (f'<div class="qr" role="img" aria-label="QR code da galeria">{_qr(url)}</div>' if url else "")
    banner = f'<p class="banner">{escape(event["banner"])}</p>' if event.get("banner") else ""
    script = (SCRIPT.replace("PHOTO_LIST", photo_list).replace("BEACON", beacon)
              .replace("REFRESH_MS", str(REFRESH_MS)).replace("HEARTBEAT_MS", str(HEARTBEAT_MS))
              .replace("SECONDS", str(SECONDS)))
    node = brand.hex_svg("node", 24)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="{brand.NAVY}">
<link rel="icon" href="{icons[0]}" sizes="16x16 32x32"><link rel="apple-touch-icon" href="{icons[1]}">
<title>Telão — {escape(event['name'])}</title>
<style>
{brand.font_face(art["font"])}
{brand.TOKENS}{CSS.replace("FONT", brand.FONT_STACK)}
</style></head>
<body>
<main class="wall">
<img class="hex hex-l" src="{art["hex_left"]}" alt="" width="84" height="152">
<img class="hex hex-r" src="{art["hex_right"]}" alt="" width="180" height="164">
<div class="top"><img class="logo" src="{art["logo"]}" alt="{brand.LOGO_ALT}" width="353" height="141">{banner}</div>
<figure class="stage">
<div class="slide"><div class="blur"></div></div><div class="slide"><div class="blur"></div></div>
<p class="empty">{node}As fotos do dia aparecem aqui</p>
</figure>
<div class="foot">
<img class="skyline" src="{art["skyline"]}" alt="" width="1080" height="250">
<div class="when" hidden><div class="stamp"><span class="time"></span>{node}</div>
<div class="what"><p class="moment"><span class="new" hidden>Nova</span><span class="nm"></span></p><p class="by"></p></div></div>
<div class="invite">{qr}<div><p class="call">Ache suas fotos</p>
<p class="how">{"Aponte a câmera do celular ou acesse" if url else "Na galeria do evento"}</p>
{f'<p class="address">{escape(address)}</p>' if url else ""}</div></div>
</div>
<button class="go">Tela cheia</button>
</main>
<script>{script}</script>
</body></html>"""
