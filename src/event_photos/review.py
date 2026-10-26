"""Local review page: the photographer confirms the selection before anything is published.

Served on 127.0.0.1 by default, from the run folder; the call blocks until "Aprovar"
is pressed and returns the overrides (photo name → keep) that differ from the
automatic decision. With face search on, photos can also be marked as showing
a minor, which keeps them out of the face index. Page text is user-facing, so
it is in Portuguese.

review.json: {"keep": {name: bool}, "minors": [name]}; older runs stored the
keep map alone, and still load.

In a container, EVENT_PHOTOS_REVIEW_HOST=0.0.0.0 makes the page reachable through the
published port (bind that port to the host's 127.0.0.1 and open it over an SSH tunnel);
no browser is opened then.

The page lives under a random token (/<token>/review.html) and only answers requests addressed
to 127.0.0.1 or localhost, so another site open in the same browser can neither read the photos
(DNS rebinding) nor approve a selection on its own (CSRF).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import webbrowser
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REVIEW_FILE = "review.json"
LOOPBACK = "127.0.0.1"
MAX_BODY = 5 * 1024 * 1024  # bytes; a keep map for thousands of photos is well under this


def new_token() -> str:
    return secrets.token_urlsafe(16)


def _read(run_dir: Path) -> dict:
    path = run_dir / REVIEW_FILE
    data = json.loads(path.read_text()) if path.exists() else {}
    if "keep" not in data and "minors" not in data:  # older flat {name: keep} file
        data = {"keep": data, "minors": []}
    return data


def load_review(run_dir: Path) -> dict[str, bool]:
    return dict(_read(run_dir).get("keep", {}))


def load_minors(run_dir: Path) -> set[str]:
    """Photos marked as showing a minor: never sent to the face index."""
    return set(_read(run_dir).get("minors", []))


def review(run_dir: Path, title: str, port: int = 8766, open_browser: bool = True,
           ask_minors: bool = False, face_counts: dict[str, int] | None = None) -> dict[str, bool]:
    metrics = json.loads((run_dir / "metrics.json").read_text())
    rows = metrics["photos"]
    frame = (metrics["stats"].get("frames") or [{"key": ""}])[0]["key"]
    minors = load_minors(run_dir)
    (run_dir / "review.html").write_text(_page(title, rows, frame, minors if ask_minors else None, face_counts or {}), encoding="utf-8")
    result: dict[str, bool] = {}
    done = threading.Event()
    token = new_token()
    prefix = f"/{token}/"
    hosts = {f"{LOOPBACK}:{port}", f"localhost:{port}"}

    class Handler(SimpleHTTPRequestHandler):
        def _admitted(self) -> bool:
            """Addressed to this machine and under the token; the path is left without the token."""
            if self.headers.get("Host") not in hosts:
                self.send_error(403)
                return False
            if not self.path.startswith(prefix):
                self.send_error(404)
                return False
            self.path = "/" + self.path[len(prefix):]
            return True

        def do_GET(self):  # noqa: N802 (http.server naming)
            if self._admitted():
                super().do_GET()

        def do_HEAD(self):  # noqa: N802
            if self._admitted():
                super().do_HEAD()

        def do_POST(self):  # noqa: N802
            if not self._admitted():
                return
            if self.path != "/approve":
                self.send_error(404)
                return
            # A cross-site form or no-cors fetch cannot send JSON without a preflight, which is never answered.
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.send_error(415)
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or int(length) > MAX_BODY:
                self.send_error(400)
                return
            try:
                body = json.loads(self.rfile.read(int(length)))
                keep, marked_in = dict(body["keep"]), list(body.get("minors", []))
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            auto = {r["name"]: r["auto_keep"] for r in rows}
            result.update({name: k for name, k in keep.items() if name in auto and k != auto[name]})
            marked = sorted(n for n in marked_in if n in auto) if ask_minors else sorted(minors)
            (run_dir / REVIEW_FILE).write_text(json.dumps({"keep": result, "minors": marked}, indent=1,
                                                          ensure_ascii=False))
            self.send_response(204)
            self.end_headers()
            done.set()

        def log_message(self, *args):
            pass

    host = os.environ.get("EVENT_PHOTOS_REVIEW_HOST", LOOPBACK)
    server = ThreadingHTTPServer((host, port), partial(Handler, directory=str(run_dir)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{LOOPBACK}:{port}{prefix}review.html"
    print(f"revisão → {url}  (aguardando você aprovar)")
    if open_browser and host == LOOPBACK:
        webbrowser.open(url)
    done.wait()
    server.shutdown()
    return result


def _card(r: dict, frame_key: str, minors: set[str] | None, faces: dict[str, int]) -> str:
    stem = Path(r["output"]).stem
    after = f"previews/after/{stem}.jpg" if r["adjustments"] else f"previews/before/{stem}.jpg"
    frame = f"frames/feed/{frame_key}/{stem}.jpg" if r["adjustments"] and frame_key else ""
    notes = r["reasons"] + r["flags"]
    note = f'<p class="note">{escape(" · ".join(notes))}</p>' if notes else ""
    n = faces.get(r["name"])
    count = "" if n is None else f'<p class="faces">{n} {"rosto" if n == 1 else "rostos"}</p>'
    minor = ("" if minors is None else
             f'<label class="minor"><input type="checkbox"{" checked" if r["name"] in minors else ""}> '
             "Tem menor de idade (fora da busca)</label>")
    return (f'<figure class="card" data-name="{escape(r["name"])}" data-keep="{str(r["keep"]).lower()}" '
            f'data-photo="{after}" data-frame="{frame}"><img src="{after}" loading="lazy" alt="">'
            f'<figcaption><b>{escape(r["name"])}</b><span class="state"></span>{note}{count}{minor}</figcaption></figure>')


def _page(title: str, rows: list[dict], frame_key: str, minors: set[str] | None = None,
          faces: dict[str, int] | None = None) -> str:
    cards = "".join(_card(r, frame_key, minors, faces or {}) for r in sorted(rows, key=lambda r: (not r["keep"], r["capture_time"] or "", r["name"])))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Revisão — {escape(title)}</title>
<style>
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#111;color:#eee}}
header{{position:sticky;top:0;z-index:2;background:#111e;backdrop-filter:blur(8px);padding:14px 24px;
  border-bottom:1px solid #333;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
h1{{font-size:18px;margin:0}}.muted{{color:#9aa4b2}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;padding:16px 24px 80px}}
.card{{margin:0;background:#1b1b1b;border:3px solid #2e7d4f;border-radius:10px;overflow:hidden;cursor:pointer}}
.card[data-keep=false]{{border-color:#444}}.card[data-keep=false] img{{opacity:.45;filter:grayscale(.6)}}
.card img{{width:100%;aspect-ratio:4/5;object-fit:contain;background:#000;display:block}}
figcaption{{padding:8px 10px;font-size:13px}}.state{{float:right;font-weight:600}}
.card[data-keep=true] .state{{color:#5ccf8a}}.card[data-keep=false] .state{{color:#aaa}}
.note{{margin:4px 0 0;color:#e0b050}}
button,label{{background:#2a2a2a;color:#eee;border:1px solid #444;border-radius:8px;padding:8px 14px;cursor:pointer;font:inherit}}
#approve{{background:#f6c33b;color:#111;border:0;font-weight:700;margin-left:auto}}
.faces{{margin:4px 0 0;color:#9aa4b2}}
.minor{{display:flex;gap:8px;align-items:center;margin-top:8px;padding:8px 10px;font-size:13px}}
</style></head><body>
<header><h1>Revisão — {escape(title)}</h1><span class="muted" id="count"></span>
<label><input type="checkbox" id="frames"> Ver com moldura</label>
<span class="muted">Clique na foto para incluir ou tirar da galeria</span>
<button id="approve">Aprovar seleção</button></header>
<main>{cards}</main>
<script>
const cards=[...document.querySelectorAll(".card")];
function render(){{
  const framed=document.getElementById("frames").checked;
  cards.forEach(c=>{{const keep=c.dataset.keep==="true";
    c.querySelector(".state").textContent=keep?"Na galeria":"Fora";
    c.querySelector("img").src=framed&&c.dataset.frame?c.dataset.frame:c.dataset.photo;}});
  const n=cards.filter(c=>c.dataset.keep==="true").length;
  document.getElementById("count").textContent=n+" de "+cards.length+" na galeria";
}}
cards.forEach(c=>c.onclick=e=>{{if(e.target.closest(".minor"))return;
  c.dataset.keep=c.dataset.keep==="true"?"false":"true";render();}});
document.getElementById("frames").onchange=render;
document.getElementById("approve").onclick=async()=>{{
  const keep=Object.fromEntries(cards.map(c=>[c.dataset.name,c.dataset.keep==="true"]));
  const minors=cards.filter(c=>c.querySelector(".minor input:checked")).map(c=>c.dataset.name);
  await fetch("approve",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{keep,minors}})}});
  document.body.innerHTML='<p style="padding:40px;font-size:18px">Seleção aprovada. Pode voltar ao terminal.</p>';
}};
render();
</script></body></html>"""
