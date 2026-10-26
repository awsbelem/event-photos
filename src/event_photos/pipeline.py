"""cull → enhance → frame for a folder of photos, reusing earlier work.

Analyses are cached per source file and developed outputs are kept while the
source and the settings are unchanged, so running again during the event only
pays for the new photos. Review overrides (photo name → keep) win over the
automatic decision.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2

from . import analyze as analyze_mod
from .cull import decide, group_bursts
from .enhance import LOOKS, FiveKEnhancer, apply_lut, bake_look, read_cube
from .frames import FORMATS, FrameTemplate, frame_photo
from .imageio import (list_photos, load_camera_rendering, load_linear, read_capture_times, resize_long_side,
                      save_jpeg, to_uint8_srgb)
from .report import write_report

PREVIEW_LONG_SIDE = 1200
DEFAULT_MODELS = Path(__file__).resolve().parents[2] / "models"

_analyzer: analyze_mod.Analyzer | None = None
_enhancer: FiveKEnhancer | None = None
_templates: list[FrameTemplate] = []


@dataclass(frozen=True)
class Settings:
    strength: float = 0.7
    look: str = "none"
    frame_templates: tuple[Path, ...] = ()  # the first is the default; attendees may pick any
    workers: int = min(8, os.cpu_count() or 4)
    models: Path = DEFAULT_MODELS

    def develop_key(self) -> dict:
        return {"enhancer": "fivek", "strength": self.strength, "look": self.look,
                "frames": [_template_stamp(t) for t in self.frame_templates]}


def _template_stamp(folder: Path) -> list:
    """Changes when any file of the frame changes, so redrawn artwork re-frames cached photos."""
    files = sorted(f for f in folder.resolve().iterdir() if f.is_file())
    return [str(folder.resolve()), [[f.name, f.stat().st_size, int(f.stat().st_mtime)] for f in files]]


def _init_worker(models_dir: str, template_dirs: tuple[str, ...]) -> None:
    global _analyzer, _enhancer, _templates
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    cv2.setNumThreads(1)  # one process per core already; nested threads only contend
    _analyzer = analyze_mod.Analyzer(Path(models_dir))
    _enhancer = FiveKEnhancer(Path(models_dir))
    _templates = [FrameTemplate.load(Path(t)) for t in template_dirs]


def _signature(path: Path) -> list:
    st = path.stat()  # follows the inbox symlinks to the original
    return [str(path.resolve()), st.st_size, st.st_mtime_ns]


def _analyze_one(path: Path, out_dir: Path) -> tuple[Path, analyze_mod.Analysis]:
    cache = out_dir / "cache" / "analysis" / f"{path.name}.pkl"
    signature = _signature(path)
    if cache.exists():
        cached_signature, analysis = pickle.loads(cache.read_bytes())
        if cached_signature == signature:
            return path, analysis
    # Culling thresholds were tuned on the neutral decode, so analysis keeps it;
    # the "before" preview is what people actually saw on the phone.
    preview = resize_long_side(to_uint8_srgb(load_linear(path)), analyze_mod.ANALYSIS_LONG_SIDE)
    save_jpeg(resize_long_side(load_camera_rendering(path), PREVIEW_LONG_SIDE),
              out_dir / "previews" / "before" / f"{path.stem}.jpg", 85)
    analysis = _analyzer.analyze(preview)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps((signature, analysis)))
    return path, analysis


def _load_look(look: str):
    if look == "none":
        return None
    return bake_look(look) if look in LOOKS else read_cube(Path(look))


def _develop_one(path: Path, analysis: analyze_mod.Analysis, settings: Settings, out_dir: Path) -> tuple[Path, dict]:
    """Phone rendering + learned FiveK correction (+ optional event look).

    The phone's own rendering already has face-aware local tone mapping; in a
    blind test on 41 photos this beat both the raw decode with our own develop
    step and the phone rendering untouched.
    """
    stamp = out_dir / "cache" / "develop" / f"{path.name}.json"
    key = settings.develop_key() | {"source": _signature(path)}
    final = out_dir / "selected" / f"{path.stem}.jpg"
    if stamp.exists() and final.exists() and json.loads(stamp.read_text()) == key:
        return path, settings.develop_key()

    rgb = _enhancer.enhance(load_camera_rendering(path).astype("float32") / 255.0, settings.strength)
    lut = _load_look(settings.look)
    if lut is not None:
        rgb = apply_lut(rgb, lut)
    out = (rgb * 255.0 + 0.5).astype("uint8")
    save_jpeg(out, final, 92)
    save_jpeg(resize_long_side(out, PREVIEW_LONG_SIDE), out_dir / "previews" / "after" / f"{path.stem}.jpg", 85)
    for template in _templates:
        for fmt in FORMATS:
            frame_photo(final, out_dir / "frames" / fmt.name / template.key / f"{path.stem}.jpg", fmt, template,
                        [f.box for f in analysis.faces])
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(key))
    return path, settings.develop_key()


def process(src: Path, out: Path, settings: Settings, review: dict[str, bool] | None = None,
            notes: dict[str, list[str]] | None = None) -> dict:
    """Run the pipeline and write metrics.json + report.html. Returns the metrics.
    `notes`: extra review flags by file name (e.g. what is known about an upload)."""
    review, notes = review or {}, notes or {}
    out.mkdir(parents=True, exist_ok=True)
    photos = list_photos(src)
    if not photos:
        raise SystemExit(f"Nenhuma foto encontrada em {src}")
    timings: dict[str, float] = {}
    start = time.perf_counter()

    # rawpy uses OpenMP, which can deadlock in forked workers.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(settings.workers, mp_context=ctx, initializer=_init_worker,
                             initargs=(str(settings.models), tuple(map(str, settings.frame_templates)))) as pool:
        t = time.perf_counter()
        times = read_capture_times(photos)
        analyses = dict(pool.map(_analyze_one, photos, [out] * len(photos)))
        timings["análise"] = time.perf_counter() - t

        t = time.perf_counter()
        decisions = decide(photos, analyses, times)
        keep = {d.path: review.get(d.path.name, d.keep) for d in decisions}
        timings["seleção"] = time.perf_counter() - t

        t = time.perf_counter()
        kept = [p for p in photos if keep[p]]
        futures = [pool.submit(_develop_one, p, analyses[p], settings, out) for p in kept]
        adjustments = dict(f.result() for f in futures)
        timings["tratamento + molduras"] = time.perf_counter() - t

    rows = [{
        "name": d.path.name, "keep": keep[d.path], "auto_keep": d.keep, "reviewed": d.path.name in review,
        "score": round(d.score, 3), "group": d.group,
        "reasons": d.reasons, "flags": d.flags + notes.get(d.path.name, []), "preview": f"{d.path.stem}.jpg", "output": f"{d.path.stem}.jpg",
        "capture_time": times[d.path].isoformat() if times[d.path] else None,
        "analysis": analyses[d.path].to_dict(), "adjustments": adjustments.get(d.path),
    } for d in sorted(decisions, key=lambda d: d.path.name)]
    total = time.perf_counter() - start
    stats = {
        "total": len(photos), "kept": len(kept), "review": sum(1 for d in decisions if keep[d.path] and (d.flags or notes.get(d.path.name))),
        "rejected": len(photos) - len(kept),
        "burst_groups": sum(1 for g in group_bursts(photos, analyses, times) if len(g) > 1),
        "seconds_per_photo": total / len(photos), "timings": timings, "look": settings.look,
        "frames": [{"key": t.key, "label": t.label} for t in map(FrameTemplate.load, settings.frame_templates)],
    }
    metrics = {"stats": stats, "photos": rows}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False))
    report = write_report(out, rows, stats, settings.look)
    print(f"{len(kept)}/{len(photos)} selecionadas em {total:.1f}s → {report}")
    return metrics
