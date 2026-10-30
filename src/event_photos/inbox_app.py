"""Upload inbox, deployed as the stack's Lambda (`index.py`; stdlib + boto3 only, nothing from this package).

GET /        the upload page (user-facing, so in Portuguese); a redirect when the event has moved on (MOVED_TO)
POST /check  {"code"} → the photographer's name, or 403
POST /sign   {"code", "name", "size", "modified"} → a signed S3 form for that one file

Invite codes live in s3://<inbox>/_config/photographers.json ({code: {"slug", "name"}}), written by
`event-photos photographers`; read on every request, so removing a code revokes it at once.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from html import escape

BUCKET = os.environ.get("INBOX_BUCKET", "")
EVENT_NAME = ""  # written into the deployed copy by `event-photos inbox <slug> deploy`
BRAND: dict = {}  # same: the event artwork as data URIs ("font", "logo", "hex_left", "hex_right"), from brand.py
MOVED_TO = ""  # same, with --to: the next event's upload page, where an old link now leads
LOGO_ALT = "AWS Community Day Brasil — Edição Norte · Belém/PA"
CONFIG_KEY = "_config/photographers.json"
EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".dng"}
MAX_BYTES = 200 * 1024 * 1024  # a 48 MP ProRAW is ~75 MB
SIGNED_FOR = 900  # seconds

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        import boto3  # in the Lambda runtime; not a dependency of this package
        _s3 = boto3.client("s3")
    return _s3


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    if MOVED_TO:
        if method == "GET":
            return {"statusCode": 302, "body": "", "headers": {"location": MOVED_TO, "cache-control": "no-store"}}
        # A page left open before the move: reloading it follows the redirect.
        return _reply(410, {"error": "Os envios agora vão para outra página. Recarregue esta página."})
    if method == "GET" and path == "/":
        return _reply(200, page(), "text/html; charset=utf-8")
    if method != "POST" or path not in ("/check", "/sign"):
        return _reply(404, {"error": "Endereço não encontrado."})
    try:
        body = event.get("body") or "{}"
        req = json.loads(base64.b64decode(body) if event.get("isBase64Encoded") else body)
    except ValueError:
        return _reply(400, {"error": "Pedido inválido."})
    who = _photographer(str(req.get("code", "")))
    if who is None:
        return _reply(403, {"error": "Código não reconhecido. Confira com quem te convidou."})
    if path == "/check":
        return _reply(200, {"name": who["name"]})
    key, error = upload_key(who["slug"], str(req.get("name", "")), req.get("size"), req.get("modified"))
    if error:
        return _reply(400, {"error": error})
    # What the browser says about the file; kept on the object to judge capture time when EXIF is missing.
    meta = {"x-amz-meta-modified": str(req.get("modified", ""))[:20], "x-amz-meta-type": str(req.get("type", ""))[:60]}
    form = _client().generate_presigned_post(
        BUCKET, key, Fields=meta,
        Conditions=[["content-length-range", 1, MAX_BYTES], *({k: v} for k, v in meta.items())], ExpiresIn=SIGNED_FOR)
    return _reply(200, {"url": form["url"], "fields": form["fields"]})


def upload_key(slug: str, name: str, size, modified) -> tuple[str, str | None]:
    """Same file → same key, so a retried upload overwrites instead of duplicating.
    The size + modified-time hash keeps apart phones that name every pick `image.jpg`."""
    stem, dot, ext = name.rpartition(".")
    ext = f".{ext.lower()}" if dot else ""
    if ext not in EXTENSIONS:
        return "", "Formato não aceito. Envie JPEG, HEIC, PNG ou DNG."
    if not isinstance(size, int) or not 0 < size <= MAX_BYTES:
        return "", "Arquivo vazio ou maior que 200 MB."
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")[:60] or "foto"
    tag = hashlib.sha1(f"{size}:{modified}".encode()).hexdigest()[:6]
    return f"incoming/{slug}/{clean}-{tag}{ext}", None


def _photographer(code: str) -> dict | None:
    code = code.strip().upper()
    if not code:
        return None
    s3 = _client()
    try:
        config = json.loads(s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None
    return config.get(code)


def _reply(status: int, body, content_type: str = "application/json") -> dict:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return {"statusCode": status, "body": text,
            "headers": {"content-type": content_type, "cache-control": "no-store",
                        "x-robots-tag": "noindex, nofollow", "referrer-policy": "no-referrer",
                        "x-frame-options": "DENY", "content-security-policy": "frame-ancestors 'none'"}}


def page() -> str:
    """The upload page, naming the event so photographers know where their photos go."""
    art = BRAND
    font = (f'@font-face{{font-family:Inter;font-style:normal;font-weight:400 800;font-display:swap;'
            f'src:url({art["font"]}) format("woff2")}}' if art else "")
    artwork = (f'<img class="hex hex-l" src="{art["hex_left"]}" alt="" width="84" height="152">'
               f'<img class="hex hex-r" src="{art["hex_right"]}" alt="" width="180" height="164">'
               f'<img class="logo" src="{art["logo"]}" alt="{LOGO_ALT}" width="353" height="141">' if art else "")
    skyline = f'<img class="skyline" src="{art["skyline"]}" alt="" width="1080" height="250">' if art else ""
    html = PAGE.replace("__FONT__", font).replace("__ART__", artwork).replace("__SKYLINE__", skyline)
    if not EVENT_NAME:
        return html.replace("__TITLE__", "Enviar fotos do evento").replace("__HEADING__", "<h1>Enviar fotos do evento</h1>")
    name = escape(EVENT_NAME)
    return (html.replace("__TITLE__", f"Enviar fotos · {name}")
            .replace("__HEADING__", f'<h1>Enviar fotos</h1><p class="event">{name}</p>'))


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#091b33">
<title>__TITLE__</title>
<style>
__FONT__
:root{--navy:#091b33;--deep:#06111f;--raised:#11274a;--rule:#313453;--ink:#ffffff;--muted:#c4d0e6;--orange:#fb8617;--violet:#5446e1;--lavender:#8365c7;--good:#4cc38a;--bad:#ff6b6b;color-scheme:dark;accent-color:var(--orange);scrollbar-color:var(--rule) var(--navy)}
*{box-sizing:border-box}
body{margin:0;background:var(--navy);color:var(--ink);font:17px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;padding:max(30px,env(safe-area-inset-top)) 20px max(40px,env(safe-area-inset-bottom));
  position:relative;overflow-x:hidden}
.hex{position:absolute;top:0;height:auto;pointer-events:none;user-select:none}
.hex-l{left:0;width:clamp(28px,7.8vw,84px)}.hex-r{right:0;width:clamp(60px,16.7vw,180px)}
.logo{display:block;width:clamp(210px,58vw,300px);height:auto;margin:0 auto 40px}
main{max-width:560px;margin:0 auto}
h1{font-size:clamp(40px,11vw,60px);font-weight:800;line-height:1;letter-spacing:-.04em;margin:0 0 12px;text-wrap:balance}
p{margin:0 0 16px;color:var(--muted)}
.event{margin:0 0 24px;color:var(--muted);font-weight:600;font-size:16px}
::selection{background:var(--orange);color:var(--navy)}
:focus-visible{outline:3px solid var(--orange);outline-offset:3px}
label{display:block;font-weight:700;margin:0 0 8px}
input[type=text]{width:100%;min-height:56px;padding:12px 16px;border-radius:12px;border:1px solid var(--rule);
  background:var(--raised);color:var(--ink);caret-color:var(--orange);
  font:600 22px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em;text-transform:uppercase}
input[type=text]::placeholder{color:#8a9bbb}
input[type=text]:focus{border-color:var(--orange);outline:none}
button,.pick{display:flex;align-items:center;justify-content:center;width:100%;min-height:56px;margin-top:12px;border:0;
  border-radius:12px;font-family:inherit;font-size:17px;font-weight:700;line-height:1;cursor:pointer;
  transition:background .2s,transform .2s cubic-bezier(.16,1,.3,1)}
button:active,.pick:active{transform:scale(.98)}
.primary{background:var(--orange);color:var(--navy)}.primary:hover{background:#ff9a3d}
.secondary{background:var(--raised);color:var(--ink);border:1px solid var(--rule)}.secondary:hover{border-color:var(--orange)}
.quiet{background:none;color:var(--muted);font-weight:600;text-decoration:underline;text-decoration-color:var(--orange);
  text-underline-offset:4px;min-height:48px}
button:disabled{opacity:.55;cursor:not-allowed}button:disabled:active{transform:none}
.hello{color:var(--ink);font-weight:800;font-size:24px;letter-spacing:-.02em;margin-bottom:8px}
.err{color:var(--bad);min-height:1.5em;margin-top:10px;font-weight:600}
input[type=file]{position:absolute;width:1px;height:1px;opacity:0}
.summary{margin:24px 0 10px;color:var(--ink);font-weight:700;font-variant-numeric:tabular-nums}
.bar{height:8px;border-radius:4px;background:var(--rule);overflow:hidden}
.bar i{display:block;height:100%;background:var(--orange);transform:scaleX(0);transform-origin:left;
  transition:transform .3s cubic-bezier(.16,1,.3,1)}
ul{list-style:none;margin:12px 0 0;padding:0}
li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--rule);font-size:15px}
li span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
li span:last-child{flex:none;display:inline-flex;align-items:center;gap:7px;font-weight:600}
li span:last-child::before{content:"";width:15px;height:15px;background:currentColor;-webkit-mask:var(--hex-line) center/contain no-repeat;
  mask:var(--hex-line) center/contain no-repeat}
li .ok::before,li .fail::before{-webkit-mask-image:var(--hex-fill);mask-image:var(--hex-fill)}
li .ok{color:var(--good)}li .fail{color:var(--bad)}li .wait{color:var(--muted)}li .up{color:var(--orange)}
:root{--hex-line:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z' fill='none' stroke='%23000' stroke-width='3' stroke-linejoin='round'/%3E%3C/svg%3E");
  --hex-fill:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z'/%3E%3C/svg%3E")}
.tips{margin-top:36px;padding-top:20px;border-top:1px solid var(--rule);font-size:15px}
.skyline{display:block;width:calc(100% + 40px);max-width:600px;height:auto;margin:40px -20px 0}
@media(min-width:640px){.skyline{margin:48px auto 0;width:100%}}
.tips ul{margin:0}.tips li{display:block;position:relative;border:0;padding:5px 0 5px 24px;color:var(--muted)}
.tips li::before{content:"";position:absolute;left:0;top:10px;width:12px;height:12px;background:var(--orange);
  -webkit-mask:var(--hex-line) center/contain no-repeat;mask:var(--hex-line) center/contain no-repeat}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head>
<body>__ART__<main>
__HEADING__
<section id="login">
  <p>Digite o código que você recebeu da organização.</p>
  <label for="code">Código de fotógrafo</label>
  <input id="code" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" inputmode="text" placeholder="XXXX-XXXX">
  <button id="enter" class="primary">Continuar</button>
  <p class="err" id="loginErr" role="alert"></p>
</section>
<section id="send" hidden>
  <p class="hello" id="hello"></p>
  <p>Escolha as fotos. Elas sobem uma a uma; se a conexão cair, toque em "Tentar de novo" e só as que faltam são enviadas.</p>
  <label class="pick primary" for="files">Escolher fotos</label>
  <input id="files" type="file" multiple accept="image/heic,image/heif,image/jpeg,image/png,image/x-adobe-dng,.heic,.heif,.dng">
  <button id="retry" class="secondary" hidden>Tentar de novo</button>
  <div id="progress" hidden>
    <p class="summary" id="summary" aria-live="polite"></p>
    <div class="bar"><i id="barFill"></i></div>
    <ul id="list"></ul>
  </div>
  <button id="logout" class="quiet">Trocar código</button>
  <div class="tips"><ul>
    <li>Envie as fotos originais da câmera, não as recebidas pelo WhatsApp: ele reduz a qualidade e apaga a data.</li>
    <li>No iPhone, escolha as fotos na Galeria, em vez de "Tirar Foto": assim elas chegam originais, com data e hora.</li>
    <li>Mantenha esta tela aberta até terminar.</li>
    <li>Prefira o Wi-Fi do evento: fotos RAW passam de 50 MB cada.</li>
    <li>Aceitamos JPEG, HEIC, PNG e DNG, até 200 MB por foto.</li>
  </ul></div>
</section>
__SKYLINE__</main>
<script>
const $=id=>document.getElementById(id),PARALLEL=3;
let code=localStorage.getItem("inboxCode")||"",queue=[],lock=null;
async function api(path,body){const r=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
  const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.error||"Falha de conexão. Tente de novo.");return data;}
async function enter(value){$("loginErr").textContent="";$("enter").disabled=true;
  try{const who=await api("/check",{code:value});code=value;localStorage.setItem("inboxCode",code);
    $("hello").textContent="Olá, "+who.name+"!";$("login").hidden=true;$("send").hidden=false;}
  catch(e){$("loginErr").textContent=e.message;}finally{$("enter").disabled=false;}}
$("enter").onclick=()=>enter($("code").value.trim().toUpperCase());
$("code").onkeydown=e=>{if(e.key==="Enter")$("enter").click();};
$("logout").onclick=()=>{localStorage.removeItem("inboxCode");code="";$("send").hidden=true;$("login").hidden=false;$("code").value="";$("code").focus();};
$("files").onchange=e=>{const picked=[...e.target.files].map(f=>({file:f,state:"wait",li:null}));e.target.value="";
  queue=queue.concat(picked);picked.forEach(item=>{item.li=document.createElement("li");
    item.li.innerHTML='<span></span><span class="wait">na fila</span>';item.li.firstChild.textContent=item.file.name;$("list").append(item.li);});
  $("progress").hidden=false;run();};
$("retry").onclick=()=>{queue.forEach(i=>{if(i.state==="fail")mark(i,"wait","na fila");});run();};
function mark(item,state,text){item.state=state;const s=item.li.lastChild;s.className=state==="done"?"ok":state;s.textContent=text;summary();}
function summary(){const done=queue.filter(i=>i.state==="done").length,fail=queue.filter(i=>i.state==="fail").length;
  $("summary").textContent=done+" de "+queue.length+" enviadas"+(fail?" · "+fail+" com falha":"");
  $("barFill").style.transform="scaleX("+(queue.length?done/queue.length:0)+")";$("retry").hidden=!fail||queue.some(i=>i.state==="up");}
async function upload(item){mark(item,"up","enviando…");
  try{const f=item.file,form=await api("/sign",{code,name:f.name,size:f.size,modified:f.lastModified,type:f.type});
    const body=new FormData();Object.entries(form.fields).forEach(([k,v])=>body.append(k,v));body.append("file",f);
    const r=await fetch(form.url,{method:"POST",body});if(!r.ok)throw new Error("O envio falhou.");mark(item,"done","enviada");}
  catch(e){mark(item,"fail",e.message.length<40?e.message:"falhou");}}
async function run(){if(navigator.wakeLock&&!lock)lock=await navigator.wakeLock.request("screen").catch(()=>null);
  const workers=Array.from({length:PARALLEL},async()=>{let item;while((item=queue.find(i=>i.state==="wait")))await upload(item);});
  await Promise.all(workers);if(lock){lock.release();lock=null;}summary();}
if(code)enter(code);
</script>
</body></html>
"""
