"""Upload inbox, deployed as the stack's Lambda (`index.py`; stdlib + boto3 only, nothing from this package).

GET /        the upload page (user-facing, so in Portuguese)
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
    if not EVENT_NAME:
        return PAGE.replace("__TITLE__", "Enviar fotos do evento").replace("__HEADING__", "<h1>Enviar fotos do evento</h1>")
    name = escape(EVENT_NAME)
    return (PAGE.replace("__TITLE__", f"Enviar fotos · {name}")
            .replace("__HEADING__", f'<p class="event">{name}</p><h1>Enviar fotos</h1>'))


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#0d1117">
<title>__TITLE__</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#f0f3f6;--muted:#9aa4b2;--line:#2a313c;--accent:#f28528;--good:#3fb950;--bad:#f85149;
  color-scheme:dark;accent-color:var(--accent)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:max(24px,env(safe-area-inset-top)) 20px max(32px,env(safe-area-inset-bottom))}
main{max-width:560px;margin:0 auto}
h1{font-size:clamp(1.6rem,6vw,2.1rem);line-height:1.15;margin:8px 0 8px;text-wrap:balance}
p{margin:0 0 16px;color:var(--muted)}
.event{margin:0;color:var(--accent);font-weight:600;font-size:15px;letter-spacing:.02em}
::selection{background:var(--accent);color:#111}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
label{display:block;font-weight:600;margin:0 0 8px}
input[type=text]{width:100%;min-height:52px;padding:12px 14px;border-radius:12px;border:1px solid var(--line);
  background:var(--panel);color:var(--ink);font:600 20px/1 ui-monospace,SFMono-Regular,monospace;letter-spacing:.08em;text-transform:uppercase}
button,.pick{display:flex;align-items:center;justify-content:center;width:100%;min-height:52px;margin-top:12px;border:0;
  border-radius:12px;font-family:inherit;font-size:17px;font-weight:600;line-height:1;cursor:pointer}
.primary{background:var(--accent);color:#111}
.secondary{background:var(--panel);color:var(--ink);border:1px solid var(--line)}
.quiet{background:none;color:var(--muted);text-decoration:underline;text-underline-offset:3px}
button:disabled{opacity:.5;cursor:default}
.hello{color:var(--ink);font-weight:600}
.err{color:var(--bad);min-height:1.5em;margin-top:8px}
input[type=file]{position:absolute;width:1px;height:1px;opacity:0}
.summary{margin:20px 0 8px;color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden}.bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .2s}
ul{list-style:none;margin:12px 0 0;padding:0}
li{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);font-size:15px}
li span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
li .ok{color:var(--good)}li .fail{color:var(--bad)}li .wait{color:var(--muted)}
.tips{margin-top:28px;font-size:15px}.tips li{display:list-item;border:0;padding:4px 0;color:var(--muted)}
.tips ul{list-style:disc;padding-left:20px}
@media (prefers-reduced-motion:reduce){.bar i{transition:none}}
</style></head>
<body><main>
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
</main>
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
  $("barFill").style.width=(queue.length?100*done/queue.length:0)+"%";$("retry").hidden=!fail||queue.some(i=>i.state==="up");}
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
