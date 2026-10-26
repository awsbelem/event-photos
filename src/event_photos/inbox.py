"""Operator side of the upload inbox: invite codes, deploying the upload page, pulling what arrived.

Everything goes through the publisher's AWS CLI profile; the machine running it only makes outbound calls.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import secrets
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

from .gallery import OWNER_SEP
from .imageio import read_capture_times
from .publish import AWS_PROFILE, stack_outputs

APP = Path(__file__).with_name("inbox_app.py")
CONFIG_KEY = "_config/photographers.json"
DATED_SUFFIX = "-dated"  # uploads-dated/: copies of EXIF-less uploads, dated from the browser
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: codes are read aloud and typed on phones


def app_source(event_name: str) -> str:
    """The upload page's Lambda code with the event's name baked in (the page shows it)."""
    line = 'EVENT_NAME = ""'
    source = APP.read_text(encoding="utf-8")
    if line not in source:
        raise RuntimeError(f"{APP.name}: {line} not found")
    return source.replace(line, f"EVENT_NAME = {json.dumps(event_name, ensure_ascii=False)}", 1)


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def slugify(name: str) -> str:
    import unicodedata
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "-".join("".join(c if c.isalnum() else " " for c in ascii_name.lower()).split()) or "fotografo"


class Inbox:
    def __init__(self, stack: str, profile: str = AWS_PROFILE):
        self.profile = profile
        outputs = stack_outputs(stack, profile)
        if "InboxBucketName" not in outputs:
            raise SystemExit(f"A stack {stack} ainda não tem a caixa de entrada. "
                             "Atualize-a no CloudFormation com o infra/aws-gallery.yaml atual.")
        self.bucket = outputs["InboxBucketName"]
        self.function = outputs["InboxFunctionName"]
        self.url = outputs["UploadUrl"]

    def _aws(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(["aws", "--profile", self.profile, *args], check=True, **kwargs)

    def photographers(self) -> dict[str, dict]:
        """{code: {"slug", "name"}}; empty before the first invite."""
        out = subprocess.run(["aws", "--profile", self.profile, "s3", "cp", f"s3://{self.bucket}/{CONFIG_KEY}", "-"],
                             capture_output=True, text=True)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}

    def save(self, config: dict[str, dict]) -> None:
        self._aws("s3", "cp", "-", f"s3://{self.bucket}/{CONFIG_KEY}", "--content-type", "application/json",
                  input=json.dumps(config, ensure_ascii=False, indent=1), text=True, capture_output=True)

    def add(self, name: str) -> tuple[str, str]:
        config = self.photographers()
        taken = {p["slug"] for p in config.values()}
        slug, n = slugify(name), 2
        while slug in taken:
            slug, n = f"{slugify(name)}-{n}", n + 1
        code = new_code()
        config[code] = {"slug": slug, "name": name}
        self.save(config)
        return code, slug

    def add_many(self, names: list[str]) -> list[tuple[str, str, str]]:
        """Invite everyone not invited yet (matched by name), in one write: [(name, code, slug)] for the new ones."""
        config = self.photographers()
        known, taken, added = {p["name"] for p in config.values()}, {p["slug"] for p in config.values()}, []
        for name in dict.fromkeys(" ".join(n.split()) for n in names if n.strip()):
            if name in known:
                continue
            slug, n = slugify(name), 2
            while slug in taken:
                slug, n = f"{slugify(name)}-{n}", n + 1
            code = new_code()
            config[code] = {"slug": slug, "name": name}
            known.add(name)
            taken.add(slug)
            added.append((name, code, slug))
        if added:
            self.save(config)
        return added

    def copy_from(self, other: "Inbox") -> int:
        """Give this event the other event's codes, so each photographer keeps one code across events."""
        config, theirs = self.photographers(), other.photographers()
        new = {code: p for code, p in theirs.items() if code not in config}
        if new:
            self.save(config | new)
        return len(new)

    def remove(self, who: str) -> list[str]:
        config = self.photographers()
        gone = [c for c, p in config.items() if who in (c, p["slug"], p["name"])]
        for c in gone:
            del config[c]
        if gone:
            self.save(config)
        return gone

    def deploy(self, event_name: str = "") -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("index.py", app_source(event_name))
        with tempfile.NamedTemporaryFile(suffix=".zip") as f:
            f.write(buf.getvalue())
            f.flush()
            self._aws("lambda", "update-function-code", "--function-name", self.function,
                      "--zip-file", f"fileb://{f.name}", capture_output=True)

    def pull(self, dest: Path, timezone: str = "America/Belem") -> tuple[dict[str, Path], dict[str, str]]:
        """Download new uploads; returns the inbox links to make ({name: file}) and {slug: name}.

        iPhone Safari strips EXIF from what it uploads. For those files a dated copy is made
        (next to `dest`) with DateTimeOriginal from the time the browser reported, which for a
        photo taken on the spot is the capture time."""
        dest.mkdir(parents=True, exist_ok=True)
        self._aws("s3", "sync", f"s3://{self.bucket}/incoming/", str(dest), "--only-show-errors")
        names = {p["slug"]: p["name"] for p in self.photographers().values()}
        files = {f"{folder.name}{OWNER_SEP}{f.name}": f
                 for folder in sorted(dest.iterdir()) if folder.is_dir()
                 for f in sorted(folder.iterdir()) if f.is_file()}
        times = read_capture_times(list(files.values()))
        dated = dest.with_name(dest.name + DATED_SUFFIX)
        for name, f in files.items():
            if times[f] is None and (copy := self._dated_copy(f, dated / f.parent.name / f.name, timezone)):
                files[name] = copy
        return files, names

    def _dated_copy(self, src: Path, dst: Path, timezone: str) -> Path | None:
        if dst.exists():
            return dst
        out = subprocess.run(["aws", "--profile", self.profile, "s3api", "head-object", "--bucket", self.bucket,
                              "--key", f"incoming/{src.parent.name}/{src.name}", "--query", "Metadata.modified",
                              "--output", "text"], capture_output=True, text=True)
        millis = out.stdout.strip()
        if out.returncode != 0 or not millis.isdigit():
            return None  # uploaded before the page recorded file times
        taken = dt.datetime.fromtimestamp(int(millis) / 1000, ZoneInfo(timezone))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        offset = taken.strftime("%z")  # -0300 → -03:00
        subprocess.run(["exiftool", "-q", "-overwrite_original", f"-DateTimeOriginal={taken:%Y:%m:%d %H:%M:%S}",
                        f"-OffsetTimeOriginal={offset[:3]}:{offset[3:]}", str(dst)], check=True)
        return dst


def sync_links(wanted: dict[str, Path], inbox: Path) -> list[Path]:
    """Make the inbox hold exactly these symlinks; drops links to photos no longer wanted."""
    inbox.mkdir(parents=True, exist_ok=True)
    for link in inbox.iterdir():
        if link.is_symlink() and link.name not in wanted:
            link.unlink()
    for name, target in wanted.items():
        link = inbox / name
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        link.unlink(missing_ok=True)
        link.symlink_to(target.resolve())
    return sorted(inbox / n for n in wanted)
