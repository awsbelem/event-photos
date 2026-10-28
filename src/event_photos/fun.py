""""Divertida": the visitor's own photo with colorful stickers, drawn in the browser and never stored.

The gallery is open to anyone, so anyone can put stickers on anyone's photo: every sticker praises the people in
it or talks about the event, never about how someone looks. Stickers come from the moment of the schedule, how
many people are in the photo, Pará and the AWS community; they sit beside the faces, never over them. Sticker
text is user-facing, so it is in Portuguese.
"""
from __future__ import annotations

import base64
import io
import json
import unicodedata
from functools import cache

from PIL import Image

from . import brand

MOMENTS = {  # sticker group → words that put a schedule title in it
    "arrive": ("credenciamento", "abertura", "boas-vindas", "check-in"),
    "learn": ("keynote", "palestra", "painel", "talk", "trilha", "workshop", "retorno"),
    "pause": ("cafe", "almoco", "intervalo", "coffee", "lanche"),
    "close": ("encerramento", "sorteio", "happy hour", "networking"),
}
STICKERS = {
    "moments": {
        "arrive": ["CHEGUEI!", "CRACHÁ OK", "BORA COMEÇAR!"],
        "learn": ["MODO APRENDIZADO", "ANOTA ESSA!", "INSPIRADO"],
        "pause": ["CAFÉ + CLOUD", "PAUSA MERECIDA", "RECARREGANDO", "TÔ BROCADO!"],
        "close": ["VALEU, BELÉM!", "ATÉ O PRÓXIMO!", "FECHOU!"],
    },
    "faces": {"1": ["PROTAGONISTA", "BRILHOU"], "2": ["DUPLA DE PESO", "PARCERIA"],
              "3": ["SQUAD", "TIME BOM", "A GALERA!"]},
    # Paraense sayings that praise or marvel. Left out: the ones that tease or brush someone off (pavulagem, mufino,
    # pitiú, liso, ralado, mangar, arreda, te sai, mas quando, disque) and mermão/mermã, which guesses a gender.
    "para": ["ÉGUA!", "PAI D'ÉGUA!", "MARRAPAZ!", "DI ROCHA!", "SÓ O CREME!", "AMO BELÉM", "AÇAÍ & CLOUD",
             "TACACÁ DEPLOY"],
    "community": ["CLOUD MOOD", "DEPLOY DE ALEGRIA", "100% UPTIME", "#CDNORTE"],
}
LOGO_WIDTH = 440  # px, drawn on the navy band in the bottom border
BELEM_WIDTH = 360  # px, the line drawing of Belém on that band


def moment_group(title: str) -> str:
    """The sticker group for a schedule title ("" when none fits: the photo then gets the general ones)."""
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return next((group for group, words in MOMENTS.items() if any(w in plain for w in words)), "")


def _png(path, width: int) -> str:
    """A PNG data URI: a canvas with an SVG drawn on it cannot be exported on older Safari."""
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.thumbnail((width, width), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


@cache
def logo_png() -> str:
    return _png(brand.ROOT / "brand" / "cd-norte" / "logo.png", LOGO_WIDTH)


@cache
def belem_png() -> str:
    return _png(brand.ROOT / "brand" / "cd-norte" / "belem.png", BELEM_WIDTH)


def script(date: str = "", place: str = "") -> str:
    """The viewer's "Divertida" mode. Needs the gallery's PHOTOS/MOMENTS, the viewer's state and the footer's skyline
    (see gallery.py). `date` and `place` are written on the band under the photo."""
    config = {"stickers": STICKERS, "logo": logo_png(), "belem": belem_png(), "date": date, "place": place}
    config = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
    return "const FUN=" + config + ";\n" + SCRIPT


CSS = """
.modes .fun-sw{position:relative;display:block;width:40px;height:50px;border-radius:5px;background:#ff4fa3}
.modes .fun-sw .ph{left:12%;top:10%;width:76%;height:68%;border-radius:2px}
.modes .fun-sw::after{content:"";position:absolute;right:-5px;top:-5px;width:20px;height:20px;background:#ffd23f;
  clip-path:polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)}
.modes button[hidden]{display:none}
@media (max-width:420px){.modes.many{grid-template-columns:repeat(var(--n,2),minmax(0,1fr))}
  .modes.many button{font-size:12px}.modes.many button>span:last-child{white-space:normal;text-align:center}}.reroll{flex:none}.reroll[hidden]{display:none}
"""

# Drawn at the size of view/<id>.webp (1800 px on the long side), which the viewer has usually loaded already.
SCRIPT = r"""
const FUN_COLORS=["#ff4fa3","#ffd23f","#23d5e6","#a6e22e","#fb8617","#8b7bff"],FUN_INK="#091b33";
let funShot=null,funJob=0,funArt=null;
const any=a=>a[Math.floor(Math.random()*a.length)];
function funTexts(p){
  const people=(p.x||[]).filter(b=>b[2]-b[0]>=.04).length,mo=MOMENTS[p.m]||{};
  const first=[...(FUN.stickers.moments[mo.g]||[]),...(FUN.stickers.faces[String(Math.min(people,3))]||[])];
  const picked=[any(first.length?first:FUN.stickers.community),any(FUN.stickers.para),any(FUN.stickers.community)];
  return picked.filter((t,i)=>picked.indexOf(t)===i);
}
function funLoad(src){return new Promise((ok,no)=>{const i=new Image();i.onload=()=>ok(i);i.onerror=no;i.src=src;});}
function funRound(c,x,y,w,h,r){r=Math.min(r,w/2,h/2);c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);
  c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();}
/* A sticker's shape and size; long texts break in two lines at the space nearest the middle. */
function funShape(c,text,size){
  c.font="800 "+size+"px Inter,sans-serif";let lines=[text];
  if(text.length>10&&text.includes(" ")){let at=-1;const mid=text.length/2;
    for(let i=0;i<text.length;i++)if(text[i]===" "&&(at<0||Math.abs(i-mid)<Math.abs(at-mid)))at=i;
    lines=[text.slice(0,at),text.slice(at+1)];}
  const lh=size*1.08,tw=Math.max(...lines.map(l=>c.measureText(l).width)),pad=size*.6;
  const shape=text.length<=8?"burst":any(["pill","bubble"]);
  let w=tw+pad*2,h=lines.length*lh+pad*1.2;
  if(shape==="burst"){w=w*1.3;h=Math.max(h*1.6,w*.55);}
  return {text,lines,lh,shape,w,h};
}
function funPath(c,s){
  c.beginPath();
  if(s.shape==="burst"){const n=13;for(let i=0;i<n*2;i++){const a=Math.PI*i/n,r=i%2?.8:1;
    c.lineTo(Math.cos(a)*s.w/2*r,Math.sin(a)*s.h/2*r);}c.closePath();return;}
  funRound(c,-s.w/2,-s.h/2,s.w,s.h,s.shape==="pill"?s.h/2:s.h*.3);
  if(s.shape==="bubble"){  /* the tail points at the people */
    const [dx,dy]=s.tail,len=Math.hypot(dx,dy)||1,ux=dx/len,sg=dy>=0?1:-1,y0=sg*s.h/2,base=s.h*.22;
    const bx=Math.max(-s.w/2+s.h*.5,Math.min(s.w/2-s.h*.5,ux*s.w*.3));
    c.moveTo(bx-base,y0-sg*4);c.lineTo(bx+ux*s.h*.4,y0+sg*s.h*.55);c.lineTo(bx+base,y0-sg*4);c.closePath();}
}
function funSticker(c,s,size){
  c.save();c.translate(s.x,s.y);c.rotate(s.rot);funPath(c,s);c.lineJoin="round";
  c.shadowColor="rgba(0,0,0,.35)";c.shadowBlur=size*.5;c.shadowOffsetY=size*.15;
  c.lineWidth=size*.34;c.strokeStyle="#fff";c.stroke();c.shadowColor="transparent";
  c.fillStyle=s.color;c.fill();
  c.fillStyle=FUN_INK;c.textAlign="center";c.textBaseline="middle";c.font="800 "+size+"px Inter,sans-serif";
  s.lines.forEach((l,i)=>c.fillText(l,0,(i-(s.lines.length-1)/2)*s.lh+size*.04));
  c.restore();
}
const funHits=(a,b)=>a[0]<b[2]&&b[0]<a[2]&&a[1]<b[3]&&b[1]<a[3];
/* Everything a sticker paints, as a box around (x, y): its shape tilted by its rotation, the white outline, the
   bubble's tail (on the side facing the people, `down` when they are below) and a little air. */
function funBox(s,x,y,down,size){
  const o=size*.34/2+size*.25,cos=Math.abs(Math.cos(s.rot)),sin=Math.abs(Math.sin(s.rot));
  const hw=s.w/2+o,hh=s.h/2+o,tail=s.shape==="bubble"?s.h*.55:0;
  const ex=cos*hw+sin*(hh+tail),ey=sin*hw+cos*hh;
  return [x-ex,y-ey-(down?0:cos*tail),x+ex,y+ey+(down?cos*tail:0)];
}
/* Beside the faces, never over them: random spots, the ones touching a face or another sticker dropped, the
   closest to the people kept (with some luck mixed in, so "Trocar" really changes things). */
function funPlace(s,faces,taken,area,size){
  const fx=faces.length?[Math.min(...faces.map(f=>f[0])),Math.min(...faces.map(f=>f[1])),
    Math.max(...faces.map(f=>f[2])),Math.max(...faces.map(f=>f[3]))]:null;
  let best=null;
  for(let i=0;i<400;i++){
    const x=area[0]+Math.random()*(area[2]-area[0]),y=area[1]+Math.random()*(area[3]-area[1]);
    const down=fx?(fx[1]+fx[3])/2>=y:true,box=funBox(s,x,y,down,size);
    if(box[0]<area[0]||box[1]<area[1]||box[2]>area[2]||box[3]>area[3])continue;
    if(faces.some(f=>funHits(box,f))||taken.some(t=>funHits(box,t)))continue;
    const d=fx?Math.hypot(Math.max(fx[0]-x,0,x-fx[2]),Math.max(fx[1]-y,0,y-fx[3]))
      :Math.min(Math.hypot(x-area[0],y-area[1]),Math.hypot(x-area[2],y-area[1]),Math.hypot(x-area[0],y-area[3]),
        Math.hypot(x-area[2],y-area[3]));
    const score=d+Math.random()*size*6;
    if(!best||score<best.score)best={x,y,box,score};
  }
  if(!best)return false;
  s.x=best.x;s.y=best.y;taken.push(best.box);
  s.tail=fx?[(fx[0]+fx[2])/2-s.x,(fx[1]+fx[3])/2-s.y]:[-1,1];
  return true;
}
/* The navy band under the photo: logo, date and place, the drawing of Belém (when there is room) and the skyline
   with its sun at the right end. Returns the band's top. */
function funBand(c,x,y,w,h,logo,belem,sky){
  c.save();c.beginPath();funRound(c,x,y,w,h,h/2);c.fillStyle=FUN_INK;c.fill();c.clip();
  const lh=h*.66,lw=lh*logo.naturalWidth/logo.naturalHeight,gap=h*.3;
  c.drawImage(logo,x+gap*1.2,y+(h-lh)/2,lw,lh);
  let tx=x+gap*1.2+lw+gap,fs=h*.22;
  const lines=[[FUN.date,"700",FUN_COLORS[4]],[FUN.place,"500","#fff"]].filter(l=>l[0]);
  const measure=()=>Math.max(0,...lines.map(([t,wt])=>{c.font=wt+" "+fs+"px Inter,sans-serif";return c.measureText(t).width;}));
  const skyMin=h*1.7,sw=h*sky.naturalWidth/sky.naturalHeight;  /* at least the sun and the cathedral's tower */
  const bh=h*.74,bw=bh*belem.naturalWidth/belem.naturalHeight;
  const fits=extra=>tx+measure()+gap+extra<=x+w;
  while(fs>h*.17&&!fits(skyMin+bw+gap))fs*=.95;  /* the drawing of Belém is worth a slightly smaller text */
  c.textAlign="left";c.textBaseline="middle";
  lines.forEach(([t,wt,col],i)=>{c.font=wt+" "+fs+"px Inter,sans-serif";c.fillStyle=col;
    c.fillText(t,tx,y+h/2+(i-(lines.length-1)/2)*fs*1.3);});
  const from=tx+(lines.length?measure()+gap:0),room=x+w-from,drawing=room-bw-gap>=skyMin;
  const skyRoom=drawing?Math.min(sw,room-bw-gap):room,sky0=x+w-skyRoom;
  if(drawing){c.globalAlpha=.6;c.drawImage(belem,from+(sky0-from-bw)/2,y+(h-bh)/2+h*.04,bw,bh);c.globalAlpha=1;}
  /* Right-aligned; when it doesn't fit, the sun stays in the middle of its room and the cranes give way. */
  const sx=Math.max(x+w-sw,sky0+skyRoom/2-sw*.49);
  c.beginPath();c.rect(sky0,y,skyRoom,h);c.clip();c.drawImage(sky,sx,y,sw,h);
  const f0=Math.max(sky0,sx),fade=c.createLinearGradient(f0,0,f0+h*.6,0);
  fade.addColorStop(0,FUN_INK);fade.addColorStop(1,FUN_INK+"00");c.fillStyle=fade;c.fillRect(sky0,y,f0-sky0+h*.6,h);
  c.restore();return y;
}
async function funMake(p){
  await Promise.all(["800 64px Inter","700 64px Inter","500 64px Inter"].map(f=>document.fonts.load(f)));
  /* The skyline is the footer's own image: no second copy in the page. */
  funArt=funArt||Promise.all([FUN.logo,FUN.belem,document.querySelector(".skyline").src].map(funLoad));
  const [im,[logo,belem,sky]]=await Promise.all([funLoad("view/"+p.id+".webp"),funArt]);
  const W=im.naturalWidth,H=im.naturalHeight,short=Math.min(W,H),B=Math.round(short*.05),BB=Math.round(short*.15);
  const cv=document.createElement("canvas");cv.width=W+2*B;cv.height=H+B+BB;const c=cv.getContext("2d");
  const colors=[...FUN_COLORS].sort(()=>Math.random()-.5),bg=colors.shift();
  c.fillStyle=bg;c.fillRect(0,0,cv.width,cv.height);
  for(let i=0;i<70;i++){c.fillStyle=any(colors);c.beginPath();  /* confetti on the border */
    const x=Math.random()*cv.width,y=Math.random()*cv.height,r=short*(.006+Math.random()*.01);
    if(i%2)c.arc(x,y,r,0,7);else{c.save();c.translate(x,y);c.rotate(Math.random()*7);c.rect(-r,-r*.5,r*2,r);c.restore();}
    c.fill();}
  c.save();c.beginPath();funRound(c,B,B,W,H,B*.5);c.clip();c.drawImage(im,B,B);c.restore();
  const ly=funBand(c,B,H+B+BB*.08,W,BB*.84,logo,belem,sky);
  /* The detector boxes the face tightly (brows to chin): grow it to cover hair, ears and chin. */
  const size=Math.round(short*.058),grow=f=>{const fw=(f[2]-f[0])*W,fh=(f[3]-f[1])*H;
    return [f[0]*W+B-fw*.35,f[1]*H+B-fh*.6,f[2]*W+B+fw*.35,f[3]*H+B+fh*.35];};
  const faces=(p.x||[]).map(grow),area=[B*.4,B*.4,cv.width-B*.4,H+B*1.4];
  const taken=[[B-size,ly-size,B+W+size,cv.height]];  /* the band stays in sight */
  funTexts(p).forEach((t,i)=>{const s=funShape(c,t,size);s.color=colors[i%colors.length];
    s.rot=(Math.random()-.5)*.35;if(funPlace(s,faces,taken,area,size))funSticker(c,s,size);
    else{const t2=funShape(c,t,size*.8);Object.assign(t2,{color:s.color,rot:s.rot});  /* no room: one size down */
      if(funPlace(t2,faces,taken,area,size*.8))funSticker(c,t2,size*.8);}});
  const blob=await new Promise(ok=>cv.toBlob(ok,"image/jpeg",.9));
  if(!blob)throw new Error("canvas");
  return URL.createObjectURL(blob);
}
/* Shows the photo's fun version, made now unless this photo already has one; a newer request wins. */
async function funShow(p){
  const job=++funJob;stage.classList.add("loading");
  try{const url=await funMake(p);if(job!==funJob){URL.revokeObjectURL(url);return;}
    if(funShot)URL.revokeObjectURL(funShot.url);funShot={id:p.id,url};
    if(VIEW[index]===p&&mode==="fun")show(index);}
  catch(e){if(job!==funJob)return;stage.classList.remove("loading");mode="photo";show(index);
    say("Não deu para montar a versão divertida.");}
}
reroll.onclick=()=>{const p=VIEW[index];hit("reroll",{id:p.id});funShow(p);};
"""
