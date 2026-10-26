"""Blind A/B/C/D comparison of treatments for the photos kept by a previous run.

  uv run python scripts/blind_compare.py <photos dir> <previous run dir> <output dir>

Versions (shuffled per photo, labels hidden until revealed):
  phone    the phone's own rendering
  current  the current develop pipeline (from the previous run)
  fivek    phone rendering + FiveK adaptive LUT
  look     fivek + the event look
Picks are stored in the browser and can be downloaded as JSON.
"""
from __future__ import annotations

import json
import random
import sys
from html import escape
from pathlib import Path

import numpy as np
from PIL import Image

from event_photos.enhance import FiveKEnhancer, apply_lut, bake_look, write_cube
from event_photos.imageio import load_camera_rendering, resize_long_side, save_jpeg

LONG_SIDE = 1600
FIVEK_STRENGTH = 0.7
LOOK = "warm-clean"
LABELS = {"phone": "iPhone (original)", "current": "Tratamento atual",
          "fivek": "IA FiveK", "look": "IA FiveK + look do evento"}


def main(photos_dir: Path, run_dir: Path, out: Path) -> None:
    rows = json.loads((run_dir / "metrics.json").read_text())["photos"]
    kept = [r for r in rows if r["keep"]]
    enhancer = FiveKEnhancer(Path(__file__).resolve().parents[1] / "models")
    look_lut = bake_look(LOOK)
    write_cube(look_lut, out / f"{LOOK}.cube", LOOK)
    rng = random.Random(31102026)
    items = []
    for r in kept:
        stem = Path(r["name"]).stem
        phone = resize_long_side(load_camera_rendering(photos_dir / r["name"]), LONG_SIDE).astype(np.float32) / 255
        fivek = enhancer.enhance(phone, FIVEK_STRENGTH)
        current = np.asarray(Image.open(run_dir / "selected" / r["output"]).convert("RGB"))
        versions = {
            "phone": phone, "fivek": fivek, "look": apply_lut(fivek, look_lut),
            "current": resize_long_side(current, LONG_SIDE).astype(np.float32) / 255,
        }
        order = list(versions)
        rng.shuffle(order)
        for i, key in enumerate(order, 1):
            save_jpeg((versions[key] * 255 + 0.5).astype(np.uint8), out / "img" / f"{stem}-{i}.jpg", 88)
        items.append({"stem": stem, "name": r["name"], "order": order})
        print(f"{len(items)}/{len(kept)} {r['name']}")
    (out / "key.json").write_text(json.dumps(items, indent=1))
    (out / "index.html").write_text(_html(items), encoding="utf-8")
    print(out / "index.html")


def _html(items: list[dict]) -> str:
    cards = "".join(f"""<section data-stem="{escape(i['stem'])}"><h2>{escape(i['name'])}</h2><div class="opts">
{''.join(f'<figure data-n="{n}"><img src="img/{escape(i["stem"])}-{n}.jpg" loading="lazy" alt=""><figcaption>{n}</figcaption></figure>' for n in range(1, 5))}
</div></section>""" for i in items)
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Comparação às cegas — tratamento</title>
<style>
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#111;color:#eee}}
header{{position:sticky;top:0;z-index:2;background:#111e;padding:14px 24px;border-bottom:1px solid #333;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
h1{{font-size:18px;margin:0}}h2{{font-size:14px;font-weight:600;margin:0 0 8px;color:#aaa}}
main{{padding:16px 24px 80px}}section{{margin-bottom:36px}}
.opts{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}@media(min-width:1500px){{.opts{{grid-template-columns:repeat(4,1fr)}}}}
figure{{margin:0;position:relative;cursor:pointer;border:3px solid transparent;border-radius:6px;overflow:hidden}}
figure img{{width:100%;display:block}}figcaption{{position:absolute;top:6px;left:8px;background:#000a;padding:0 8px;border-radius:99px}}
figure.picked{{border-color:#f0a020}}figure .label{{position:absolute;bottom:6px;left:8px;background:#000c;padding:1px 8px;border-radius:4px;font-size:13px}}
button{{background:#2a2a2a;color:#eee;border:1px solid #444;border-radius:6px;padding:6px 12px;cursor:pointer}}
#score{{color:#f0a020}}.zoom{{position:fixed;inset:0;background:#000;z-index:5;display:flex}}.zoom img{{margin:auto;max-width:100%;max-height:100%}}
</style>
<header><h1>Qual tratamento ficou melhor?</h1><span>Clique na melhor versão de cada foto · duplo clique amplia</span>
<span id="progress"></span><button id="reveal">Revelar versões</button><button id="export">Baixar escolhas</button><span id="score"></span></header>
<main>{cards}</main>
<script>
const KEY={json.dumps({i["stem"]: i["order"] for i in items})};
const LABELS={json.dumps(LABELS, ensure_ascii=False)};
const picks=JSON.parse(localStorage.getItem("blind-picks")||"{{}}");
function render(){{
  document.querySelectorAll("section").forEach(s=>s.querySelectorAll("figure").forEach(f=>
    f.classList.toggle("picked",picks[s.dataset.stem]==f.dataset.n)));
  document.getElementById("progress").textContent=Object.keys(picks).length+"/"+Object.keys(KEY).length+" escolhidas";
}}
document.querySelectorAll("figure").forEach(f=>{{
  f.addEventListener("click",()=>{{picks[f.closest("section").dataset.stem]=f.dataset.n;localStorage.setItem("blind-picks",JSON.stringify(picks));render();}});
  f.addEventListener("dblclick",()=>{{const z=document.createElement("div");z.className="zoom";z.innerHTML=`<img src="${{f.querySelector("img").src}}">`;z.onclick=()=>z.remove();document.body.append(z);}});
}});
document.getElementById("reveal").onclick=()=>{{
  const tally={{}};
  document.querySelectorAll("section").forEach(s=>s.querySelectorAll("figure").forEach(f=>{{
    const v=KEY[s.dataset.stem][f.dataset.n-1];
    if(!f.querySelector(".label"))f.insertAdjacentHTML("beforeend",`<span class="label">${{LABELS[v]}}</span>`);
  }}));
  for(const [stem,n] of Object.entries(picks)){{const v=KEY[stem][n-1];tally[v]=(tally[v]||0)+1;}}
  document.getElementById("score").textContent=Object.entries(tally).sort((a,b)=>b[1]-a[1]).map(([v,c])=>LABELS[v]+": "+c).join(" · ");
}};
document.getElementById("export").onclick=()=>{{
  const data=Object.entries(picks).map(([stem,n])=>({{stem,choice:KEY[stem][n-1]}}));
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,1)],{{type:"application/json"}}));a.download="escolhas.json";a.click();
}};
render();
</script></html>"""


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:4]))
