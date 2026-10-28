"""Command line: `event` runs the whole flow for one event; the other commands are its steps."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

from .enhance import LOOKS
from .faces import (FACE_ACK, FACE_COUNTS, FACE_STATE, FaceStack, deletion_time, face_search_config,
                    missing_preconditions)
from .frames import DEFAULT_TEMPLATE, FRAMES_DIR
from .gallery import FRAME_FORMATS, OWNER_SEP, PHOTO_LIST, build_gallery, load_event, local_path, parse_offset
from .imageio import read_capture_times, read_image_sizes
from .inbox import DATED_SUFFIX, Inbox, slugify, sync_links
from .pipeline import DEFAULT_MODELS, Settings, process
from . import publish as publish_mod
from . import stats as stats_mod
from .review import load_minors, load_review, review

ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = ROOT / "events"
EVENTS_OUT = ROOT / "out" / "events"
ROUNDS = "rounds.jsonl"  # in the event's out folder: one line per publish, for the event report
DEFAULT_WORKERS = int(os.environ.get("EVENT_PHOTOS_WORKERS", min(8, os.cpu_count() or 4)))


def run(args: argparse.Namespace) -> None:
    settings = Settings(args.strength, args.look, tuple(args.frame_template or [DEFAULT_TEMPLATE]), args.workers, args.models)
    process(Path(args.input), Path(args.output), settings)


def event(args: argparse.Namespace) -> None:
    """Photographers' uploads → selection → your review → gallery (→ publish with --publish)."""
    config_path = EVENTS_DIR / args.slug / "event.json"
    config = load_event(config_path)
    work = EVENTS_OUT / args.slug
    face_search_config(config)  # fail fast on invalid settings, before any processing

    inbox = _inbox_for(config)
    if not inbox:
        raise SystemExit(f"Defina \"aws_stack\" em {config_path}: as fotos chegam pela página de envio.")
    owner = slugify(config.get("photographer", ""))
    names = {owner: config["photographer"]} if owner else {}
    wanted, uploaders = inbox.pull(work / "uploads", config.get("timezone", "America/Belem"))
    names |= uploaders
    print(f"Envios: {len(wanted)} fotos de {len({n.split(OWNER_SEP)[0] for n in wanted})} fotógrafo(s)")
    if not wanted:
        raise SystemExit("Nenhuma foto: peça aos fotógrafos que enviem pela página de envio "
                         "(você também, com o seu código).")
    sync_links(wanted, work / "inbox")
    config["photographers"] = names

    names = config.get("frames") or ([config["frame"]] if config.get("frame") else [])
    templates = tuple(FRAMES_DIR / n for n in names) or (DEFAULT_TEMPLATE,)
    settings = Settings(strength=config.get("strength", 0.7), frame_templates=templates, workers=args.workers)
    run_dir = work / "run"
    previous = load_review(run_dir)
    notes = review_notes(wanted, dt.date.fromisoformat(config["date"]))
    process(work / "inbox", run_dir, settings, previous, notes)
    if not args.skip_review:
        enabled = face_search_config(config).enabled
        overrides = review(run_dir, config["name"], ask_minors=enabled,
                           face_counts=_face_counts(config, run_dir, args.slug) if enabled else None)
        if overrides != previous:
            process(work / "inbox", run_dir, settings, overrides, notes)

    site = work / "site"
    if args.publish and (face_ui := _sync_faces(config, run_dir, args.slug)):
        config["face_search_ui"] = face_ui
    if config.get("aws_stack"):  # the venue screen's QR points at the published gallery
        try:
            profile = config.get("aws_profile", publish_mod.AWS_PROFILE)
            config["url"] = publish_mod.stack_outputs(config["aws_stack"], profile)["Url"]
        except (subprocess.CalledProcessError, KeyError, OSError):
            print("aviso: endereço da galeria indisponível; o telão fica sem QR code")
    build_gallery(run_dir, site, config)
    _export_frames(run_dir, work / "instagram")
    print(f"galeria → {site / 'index.html'}")
    print(f"molduras para postar → {work / 'instagram'}")
    if args.publish:
        if config.get("aws_stack"):
            url = publish_mod.aws(site, config["aws_stack"], config.get("aws_profile", publish_mod.AWS_PROFILE))
            print(f"publicado → {url}")
        elif config.get("pages_project"):
            publish_mod.cloudflare_pages(site, config["pages_project"])
        else:
            raise SystemExit(f"Defina \"aws_stack\" ou \"pages_project\" em {config_path} para publicar.")
        record_round(work / ROUNDS, site, len(wanted), config.get("timezone", "America/Belem"))
    else:
        print(f"ver no computador: python3 -m http.server -d {site} -b 127.0.0.1 8765")


def record_round(log: Path, site: Path, uploads: int, timezone: str, now: dt.datetime | None = None) -> dict:
    """Append this publish to the event's rounds log: when, how many uploads, and which photos went out for the
    first time. Each publish replaces photos.json, so this is the only record of when a photo reached the gallery."""
    from zoneinfo import ZoneInfo
    seen = set()
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.update(json.loads(line)["new"])
    ids = [p["id"] for p in json.loads((site / PHOTO_LIST).read_text(encoding="utf-8"))["photos"]]
    when = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(timezone))
    entry = {"published": when.isoformat(timespec="seconds"), "uploads": uploads,
             "new": [i for i in ids if i not in seen], "total": len(ids)}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


LOW_RES_LONG_SIDE = 2000  # px; WhatsApp sends 1600, phones shoot 4000+


def review_notes(files: dict[str, Path], event_day: dt.date) -> dict[str, list[str]]:
    """What the reviewer should know about each photo: estimated time, low resolution, other day."""
    paths = list(files.values())
    times, sizes = read_capture_times(paths), read_image_sizes(paths)
    notes: dict[str, list[str]] = {}
    for name, path in files.items():
        found = []
        if path.parent.parent.name.endswith(DATED_SUFFIX):
            found.append("Horário estimado pelo envio (a foto chegou sem data)")
        if (size := sizes[path]) and max(size) < LOW_RES_LONG_SIDE:
            found.append(f"Baixa resolução ({size[0]}×{size[1]}), possivelmente repassada pelo WhatsApp")
        if (taken := times[path]) and taken.date() != event_day:
            found.append(f"Tirada em {taken:%d/%m}, fora do dia do evento")
        if found:
            notes[name] = found
    return notes


def published_photos(run_dir: Path) -> tuple[dict[str, Path], set[str]]:
    """Gallery photo id → developed JPEG for every approved photo, and the ids marked as minors."""
    rows = json.loads((run_dir / "metrics.json").read_text())["photos"]
    photos = {Path(r["output"]).stem: run_dir / "selected" / r["output"] for r in rows if r["keep"]}
    by_name = {r["name"]: Path(r["output"]).stem for r in rows}
    return photos, {by_name[n] for n in load_minors(run_dir) if n in by_name}


def face_images(run_dir: Path) -> dict[str, Path]:
    """Photo name → the image its faces are counted on: the developed photo, which is what gets indexed (a small
    face the 1200 px preview misses can show at the 1920 px sent), or the preview for photos not developed."""
    rows = json.loads((run_dir / "metrics.json").read_text())["photos"]
    images = {}
    for r in rows:
        candidates = [run_dir / "selected" / r["output"]] if r["keep"] else []
        candidates += [run_dir / "previews" / kind / r["preview"] for kind in ("after", "before")]
        if found := next((c for c in candidates if c.exists()), None):
            images[r["name"]] = found
    return images


def _face_counts(config: dict, run_dir: Path, slug: str) -> dict[str, int] | None:
    """Faces per photo for the review; None when Rekognition is unreachable (the review still opens)."""
    try:
        stack = FaceStack.load(face_search_config(config).stack, config.get("aws_profile", publish_mod.AWS_PROFILE), slug)
        return stack.index.counts(face_images(run_dir), run_dir / FACE_COUNTS)
    except Exception as exc:
        print(f"aviso: contagem de rostos indisponível ({type(exc).__name__}).")
        return None


def _sync_faces(config: dict, run_dir: Path, slug: str) -> dict | None:
    """Keep the face index in step with what is being published and return what the gallery needs
    to offer the search; None (no button) when it is off or unavailable. Never blocks publishing."""
    settings = face_search_config(config)
    if not settings.enabled:
        return None
    try:
        stack = FaceStack.load(settings.stack, config.get("aws_profile", publish_mod.AWS_PROFILE), slug)
        if not stack.index.exists():
            print("aviso: a coleção de rostos não existe; rode `event-photos face-search <evento> enable`. "
                  "Publicando sem a busca por rosto.")
            return None
        photos, minors = published_photos(run_dir)
        # A photo the count found no face in, on the very image that would be sent, has nothing to index: the
        # index call would cost and add nothing. A photo not counted (Rekognition failed) is still sent.
        counts = stack.index.counts(face_images(run_dir), run_dir / FACE_COUNTS)
        stems = {r["name"]: Path(r["output"]).stem for r in json.loads((run_dir / "metrics.json").read_text())["photos"]}
        faceless = {stems[n] for n, k in counts.items() if k == 0 and n in stems}
        print(stack.index.sync(photos, minors | faceless, run_dir / FACE_STATE).summary())
    except Exception as exc:  # the gallery must go out even if Rekognition is unreachable
        print(f"aviso: busca por rosto não atualizada ({type(exc).__name__}: {exc}). Publicando sem a busca.")
        return None
    indexed = json.loads((run_dir / FACE_STATE).read_text())["photos"]
    return {"url": stack.outputs["SearchUrl"], "photo": settings.photo,
            "ids": {v["external"]: pid for pid, v in indexed.items() if v["external"] != pid},
            "until": f"{deletion_time(config['date'], settings.retention_days):%d/%m/%Y}"}


def _inbox_for(config: dict) -> Inbox | None:
    if not config.get("aws_stack"):
        return None
    try:
        return Inbox(config["aws_stack"], config.get("aws_profile", publish_mod.AWS_PROFILE))
    except SystemExit as missing:
        print(f"aviso: {missing}")
        return None


def _export_frames(run_dir: Path, dest: Path) -> None:
    """The approved photos' frames, ready to post."""
    metrics = json.loads((run_dir / "metrics.json").read_text())
    shutil.rmtree(dest, ignore_errors=True)
    for frame in metrics["stats"].get("frames", []):
        for fmt in FRAME_FORMATS:
            (dest / frame["key"] / fmt).mkdir(parents=True)
            for r in metrics["photos"]:
                framed = run_dir / "frames" / fmt / frame["key"] / r["output"]
                if r["keep"] and framed.exists():
                    shutil.copyfile(framed, dest / frame["key"] / fmt / r["output"])


def gallery(args: argparse.Namespace) -> None:
    offset = parse_offset(args.clock_offset)
    page = build_gallery(Path(args.run), Path(args.site), load_event(Path(args.event)), offset)
    print(f"galeria → {page}")


def publish(args: argparse.Namespace) -> None:
    if args.aws_stack:
        print(f"publicado → {publish_mod.aws(Path(args.site), args.aws_stack, args.aws_profile)}")
    else:
        publish_mod.cloudflare_pages(Path(args.site), args.project)


def _event_inbox(slug: str) -> Inbox:
    config = load_event(EVENTS_DIR / slug / "event.json")
    if not config.get("aws_stack"):
        raise SystemExit(f"Defina \"aws_stack\" em events/{slug}/event.json para usar a página de envio.")
    return Inbox(config["aws_stack"], config.get("aws_profile", publish_mod.AWS_PROFILE))


def photographers(args: argparse.Namespace) -> None:
    inbox = _event_inbox(args.slug)
    if args.action == "add":
        if not args.name:
            raise SystemExit("Informe o nome: event-photos photographers <evento> add \"Nome Sobrenome\"")
        code, slug = inbox.add(args.name)
        print(f"{args.name} convidado(a).\n  código: {code}\n  página de envio: {inbox.url}\n  "
              f"(as fotos chegam como {slug}{OWNER_SEP}…)")
    elif args.action == "add-file":
        if not args.name:
            raise SystemExit("Informe o arquivo: event-photos photographers <evento> add-file nomes.txt (um nome por linha)")
        added = inbox.add_many(Path(args.name).read_text(encoding="utf-8").splitlines())
        for name, code, _ in added:
            print(f"{code}  {name}")
        print(f"{len(added)} convidado(s); quem já estava na lista ficou como estava.\npágina de envio: {inbox.url}")
    elif args.action == "copy":
        if not args.name:
            raise SystemExit("Informe o evento de origem: event-photos photographers <evento> copy <outro evento>")
        print(f"{inbox.copy_from(_event_inbox(args.name))} código(s) copiado(s) de {args.name}; "
              "cada fotógrafo usa o mesmo código nos dois eventos.")
    elif args.action == "remove":
        gone = inbox.remove(args.name or "")
        print(f"{len(gone)} código(s) revogado(s)." if gone else f"Ninguém encontrado com \"{args.name}\".")
    else:
        people = inbox.photographers()
        for code, p in sorted(people.items(), key=lambda kv: kv[1]["name"]):
            print(f"{code}  {p['name']}  ({p['slug']})")
        print(f"página de envio: {inbox.url}" if people else "Nenhum fotógrafo convidado ainda.")


def inbox_cmd(args: argparse.Namespace) -> None:
    inbox = _event_inbox(args.slug)
    if args.action == "deploy":
        inbox.deploy(load_event(EVENTS_DIR / args.slug / "event.json")["name"])
        print(f"página de envio atualizada → {inbox.url}")
    else:
        uploads, names = inbox.pull(EVENTS_OUT / args.slug / "uploads")
        print(f"{len(uploads)} fotos recebidas → {EVENTS_OUT / args.slug / 'uploads'}")


def _set_face_search(slug: str, **changes) -> None:
    """Record face_search changes in the event's event.local.json (gitignored), keeping everything else."""
    path = local_path(EVENTS_DIR / slug / "event.json")
    raw = json.loads(path.read_text()) if path.exists() else {}
    raw["face_search"] = {**raw.get("face_search", {}), **changes}
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")


def face_search_cmd(args: argparse.Namespace) -> None:
    config = load_event(EVENTS_DIR / args.slug / "event.json")
    settings = face_search_config(config)
    if not settings.stack:
        raise SystemExit(f"Defina face_search.stack em events/{args.slug}/event.json (a stack da busca em sa-east-1).")
    work = EVENTS_OUT / args.slug
    ack = work / FACE_ACK
    if args.action == "enable":  # preconditions first: nothing is touched on AWS until they hold
        if args.confirm_ai_opt_out and not ack.exists():
            ack.parent.mkdir(parents=True, exist_ok=True)
            ack.write_text(json.dumps({"ai_opt_out_confirmed": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
        missing = missing_preconditions(config, settings, ack)
        if missing:
            raise SystemExit("A busca por rosto não pode ser ligada ainda. Falta:\n  - " + "\n  - ".join(missing))
    stack = FaceStack.load(settings.stack, config.get("aws_profile", publish_mod.AWS_PROFILE), args.slug)
    if args.action == "enable":
        stack.deploy(settings.threshold, enabled=True, photo=settings.photo)
        stack.index.ensure_collection()
        when = deletion_time(config["date"], settings.retention_days)
        stack.schedule_deletion(when, config.get("timezone", "America/Belem"))
        _set_face_search(args.slug, enabled=True)
        print(f"Busca por rosto ligada{' (selfie e foto do celular)' if settings.photo else ' (só selfie)'}. "
              f"A coleção será apagada em {when:%d/%m/%Y às %H:%M}.\n"
              "Publique de novo (event --publish) para indexar as fotos e mostrar o botão na galeria.")
    elif args.action == "disable":
        stack.configure(settings.threshold, enabled=False, photo=settings.photo)
        _set_face_search(args.slug, enabled=False)
        print("Busca por rosto desligada: a função não responde mais. Publique de novo para tirar o botão da galeria.")
    elif args.action == "purge":
        stack.purge()
        (work / "run" / FACE_STATE).unlink(missing_ok=True)
        stack.configure(settings.threshold, enabled=False, photo=settings.photo)
        _set_face_search(args.slug, enabled=False)
        print("Coleção de rostos e agendamento apagados. Publique de novo para tirar o botão da galeria.")
    else:
        count, when = stack.face_count(), stack.scheduled_for()
        state = work / "run" / FACE_STATE
        indexed = len(json.loads(state.read_text())["photos"]) if state.exists() else 0
        print(f"ligada no event.json: {'sim' if settings.enabled else 'não'}\n"
              f"coleção: {'não existe' if count is None else f'{count} rostos'}\n"
              f"fotos indexadas (estado local): {indexed}\n"
              f"busca com foto do celular: no event.json {settings.photo_ok or 'não'}; "
              f"na função {'ligada' if stack.photo_on() else 'desligada'}\n"
              f"apagamento agendado: {when or 'nenhum'}\n"
              f"endereço da busca: {stack.outputs['SearchUrl']}")


def stats_cmd(args: argparse.Namespace) -> None:
    """The event report from the gallery's CloudFront logs, the rounds log and the review state."""
    from zoneinfo import ZoneInfo
    config = load_event(EVENTS_DIR / args.slug / "event.json")
    if not config.get("aws_stack"):
        raise SystemExit(f"Defina \"aws_stack\" em events/{args.slug}/event.json: o relatório lê os logs da galeria.")
    work, profile = EVENTS_OUT / args.slug, config.get("aws_profile", publish_mod.AWS_PROFILE)
    run_dir = work / "run"
    if not (run_dir / "metrics.json").exists():
        raise SystemExit(f"Sem o estado do evento em {work}. Traga-o da instância: scripts/aws.sh pull-state {args.slug}")
    tz = ZoneInfo(config.get("timezone", "America/Belem"))
    outputs = publish_mod.stack_outputs(config["aws_stack"], profile)
    if "LogsBucketName" not in outputs:
        raise SystemExit("A stack da galeria ainda não tem o bucket de logs: atualize-a (infra/aws-gallery.yaml).")
    print("baixando os logs…")
    stats_mod.download_logs(outputs["LogsBucketName"], work / "logs", profile)
    since, until = (dt.date.fromisoformat(d) if d else None for d in (args.since, args.until))
    hits = stats_mod.read_logs(work / "logs", tz, since, until)
    base = outputs["Url"].rstrip("/")
    listing = json.loads(stats_mod.fetch(f"{base}/{PHOTO_LIST}"))

    metrics = json.loads((run_dir / "metrics.json").read_text())
    offsets = {o: parse_offset(v) for o, v in config.get("clock_offsets", {}).items()}
    taken = {}
    for r in metrics["photos"]:
        pid = Path(r["output"]).stem
        if r.get("capture_time"):  # the camera's clock, read as the event's local time, as in the gallery
            local = dt.datetime.fromisoformat(r["capture_time"]) + offsets.get(pid.partition(OWNER_SEP)[0], dt.timedelta())
            taken[pid] = local.replace(tzinfo=tz) if local.tzinfo is None else local.astimezone(tz)
    stems = {r["name"]: Path(r["output"]).stem for r in metrics["photos"]}
    minors = {stems[n] for n in load_minors(run_dir) if n in stems}
    frames = {f["key"]: f.get("label", f["key"]) for f in metrics["stats"].get("frames", [])}

    numbers = stats_mod.compute(hits, listing, stats_mod.read_rounds(work / ROUNDS), taken, frames, minors)
    wanted = {p["id"] for group in numbers["highlights"].values() for p in group}
    thumbs = {}
    for pid in wanted:
        try:
            thumbs[pid] = stats_mod.fetch(f"{base}/thumbs/{pid}.webp")
        except OSError:
            print(f"aviso: miniatura de {pid} indisponível")
    out = work / "report"
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps(numbers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "index.html").write_text(stats_mod.render(config, numbers, thumbs), encoding="utf-8")
    print(f"{len(hits)} registros · {numbers['reach']['opens']} aberturas · {numbers['find']['searches']} buscas\n"
          f"relatório → {out / 'index.html'} (imprima como PDF pelo navegador)\nnúmeros → {out / 'report.json'}")


def main() -> None:
    # AWS CLI v2 pages its output through `less` on a terminal: a run in a remote session would stop (or fail,
    # with no less installed) at the first command whose output is not captured.
    os.environ["AWS_PAGER"] = ""
    parser = argparse.ArgumentParser(prog="event-photos")
    sub = parser.add_subparsers(required=True)
    e = sub.add_parser("event", help="fluxo completo de um evento: envios → revisão → galeria")
    e.add_argument("slug", help="pasta em events/ com o event.json")
    e.add_argument("--publish", action="store_true", help="publica no S3 + CloudFront (aws_stack do event.json) ou no Cloudflare Pages (pages_project)")
    e.add_argument("--skip-review", action="store_true", help="usa a seleção automática sem abrir a revisão")
    e.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    e.set_defaults(func=event)

    ph = sub.add_parser("photographers", help="convida, lista ou revoga fotógrafos da página de envio")
    ph.add_argument("slug", help="pasta em events/ com o event.json")
    ph.add_argument("action", choices=["add", "add-file", "copy", "list", "remove"])
    ph.add_argument("name", nargs="?", help="nome (add), arquivo com um nome por linha (add-file), "
                                            "evento de origem (copy) ou nome, slug ou código (remove)")
    ph.set_defaults(func=photographers)

    ib = sub.add_parser("inbox", help="atualiza a página de envio ou baixa as fotos recebidas")
    ib.add_argument("slug", help="pasta em events/ com o event.json")
    ib.add_argument("action", choices=["deploy", "pull"])
    ib.set_defaults(func=inbox_cmd)

    fs = sub.add_parser("face-search", help="liga, desliga, apaga ou mostra a busca por rosto do evento")
    fs.add_argument("slug", help="pasta em events/ com o event.json")
    fs.add_argument("action", choices=["enable", "disable", "purge", "status"])
    fs.add_argument("--confirm-ai-opt-out", action="store_true",
                    help="confirma que a política de opt-out de serviços de IA da AWS está ativa na conta")
    fs.set_defaults(func=face_search_cmd)

    st = sub.add_parser("stats", help="relatório do evento a partir dos logs da galeria")
    st.add_argument("slug", help="pasta em events/ com o event.json")
    st.add_argument("--since", help="primeiro dia (AAAA-MM-DD), no horário do evento")
    st.add_argument("--until", help="último dia (AAAA-MM-DD), no horário do evento")
    st.set_defaults(func=stats_cmd)

    p = sub.add_parser("run", help="processa uma pasta de fotos")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--strength", type=float, default=0.7, help="intensidade da correção automática (0–1)")
    p.add_argument("--look", default="none", help=f"none, {', '.join(LOOKS)} ou caminho de um .cube")
    p.add_argument("--frame-template", type=Path, action="append", default=None,
                   help="pasta de uma moldura (repita para várias; a primeira é a padrão)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    p.set_defaults(func=run)

    g = sub.add_parser("gallery", help="gera a galeria pública a partir de uma rodada")
    g.add_argument("run", help="pasta de saída do comando run")
    g.add_argument("site", help="pasta onde a galeria será gerada")
    g.add_argument("--event", required=True, help="event.json com nome, data e programação")
    g.add_argument("--clock-offset", default="0:00",
                   help="corrige o relógio da câmera, ex.: -0:05 se ela estava 5 min adiantada")
    g.set_defaults(func=gallery)

    pub = sub.add_parser("publish", help="publica a galeria no S3 + CloudFront ou no Cloudflare Pages")
    pub.add_argument("site")
    target = pub.add_mutually_exclusive_group(required=True)
    target.add_argument("--aws-stack", help="stack criada com infra/aws-gallery.yaml")
    target.add_argument("--project", help="nome do projeto no Cloudflare Pages (vira <nome>.pages.dev)")
    pub.add_argument("--aws-profile", default=publish_mod.AWS_PROFILE, help="perfil do AWS CLI com a chave da stack")
    pub.set_defaults(func=publish)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
