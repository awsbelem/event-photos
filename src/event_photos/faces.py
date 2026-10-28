"""Face search with Amazon Rekognition (README, "Face search").

Everything that touches faces runs in sa-east-1. The feature is off unless `face_search.enabled`
is set in event.json, which the CLI only allows once the preconditions in the spec are met.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

FACES_REGION = "sa-east-1"
THRESHOLD_RANGE = (80.0, 99.9)  # similarity %; below 80 wrong matches become common
RETENTION_RANGE = (1, 90)  # days the collection is kept after the event
FACE_STATE = "face_index.json"  # in the run folder: photo id → face ids, for incremental publishes
FACE_COUNTS = "face_counts.json"  # in the run folder: faces per photo shown in the review
FACE_ACK = "face_search_ack.json"  # in the event's out folder: when the AI opt-out was confirmed


@dataclass(frozen=True)
class FaceSearchConfig:
    enabled: bool = False
    stack: str = ""
    threshold: float = 95.0
    retention_days: int = 30
    legal_ok: str | None = None  # date of the written legal opinion
    photo_ok: str | None = None  # date of the sign-off for searching with a photo from the phone (off without it)

    @property
    def photo(self) -> bool:
        return bool(self.photo_ok)


def face_search_config(event: dict) -> FaceSearchConfig:
    """The event's face search settings, with defaults; raises SystemExit on invalid values."""
    raw = event.get("face_search") or {}
    config = FaceSearchConfig(
        enabled=bool(raw.get("enabled", False)),
        stack=str(raw.get("stack", "")),
        threshold=float(raw.get("threshold", 95.0)),
        retention_days=int(raw.get("retention_days", 30)),
        legal_ok=raw.get("legal_ok"),
        photo_ok=raw.get("photo_ok") or None,
    )
    low, high = THRESHOLD_RANGE
    if not low <= config.threshold <= high:
        raise SystemExit(f"face_search.threshold deve ficar entre {low:g} e {high:g} (está {config.threshold:g}).")
    low, high = RETENTION_RANGE
    if not low <= config.retention_days <= high:
        raise SystemExit(f"face_search.retention_days deve ficar entre {low} e {high} (está {config.retention_days}).")
    if config.photo_ok:
        for key in ("legal_ok", "photo_ok"):
            if not _is_date(getattr(config, key)):
                raise SystemExit(f"face_search.photo_ok exige face_search.{key} com uma data (AAAA-MM-DD).")
    if config.enabled and not config.stack:
        raise SystemExit("face_search.enabled exige face_search.stack (a stack da busca em sa-east-1).")
    return config


def _is_date(value) -> bool:
    try:
        dt.date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


# --- face index (desktop side) ------------------------------------------------------------------

EXTERNAL_ID = re.compile(r"[a-zA-Z0-9_.\-:]{1,255}")
MAX_SIDE = 1920  # px sent to Rekognition; plenty for faces, well under its 5 MB limit
MAX_BYTES = 5 * 1024 * 1024
RETRYABLE = {"ThrottlingException", "ProvisionedThroughputExceededException", "InternalServerError"}
ATTEMPTS = 5


def external_id(photo_id: str) -> str:
    """Rekognition's ExternalImageId allows only [a-zA-Z0-9_.-:]; other ids get a stable hash."""
    if EXTERNAL_ID.fullmatch(photo_id):
        return photo_id
    return "h-" + hashlib.sha1(photo_id.encode()).hexdigest()[:16]


def error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def jpeg_bytes(path: Path) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        for quality in (85, 75, 65):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
            if buf.tell() <= MAX_BYTES:
                return buf.getvalue()
    raise ValueError(f"{path.name}: JPEG still over 5 MB")


@dataclass
class SyncReport:
    added: int = 0
    removed: int = 0
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = f"Busca por rosto: +{self.added} fotos indexadas, −{self.removed} removidas"
        return text + (f", {len(self.failed)} com falha ({', '.join(self.failed[:5])})" if self.failed else "")


class FaceIndex:
    """The event's Rekognition collection, kept in step with the published photos.

    A local state file (photo id → face ids + source signature) makes publishes incremental and lets
    an interrupted run resume; it is written after every photo."""

    def __init__(self, collection_id: str, client, sleep=time.sleep):
        self.collection_id = collection_id
        self.client = client
        self.sleep = sleep

    @classmethod
    def from_stack(cls, stack: str, profile: str) -> FaceIndex:
        import boto3
        session = boto3.Session(profile_name=profile, region_name=FACES_REGION)
        outputs = session.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
        values = {o["OutputKey"]: o["OutputValue"] for o in outputs}
        return cls(values["CollectionId"], session.client("rekognition"))

    def exists(self) -> bool:
        try:
            self.client.describe_collection(CollectionId=self.collection_id)
            return True
        except Exception as exc:
            if error_code(exc) == "ResourceNotFoundException":
                return False
            raise

    def ensure_collection(self) -> None:
        if not self.exists():
            self.client.create_collection(CollectionId=self.collection_id)

    def _call(self, method: str, **kwargs):
        for attempt in range(ATTEMPTS):
            try:
                return getattr(self.client, method)(**kwargs)
            except Exception as exc:
                if error_code(exc) not in RETRYABLE or attempt == ATTEMPTS - 1:
                    raise
                self.sleep(0.5 * 2 ** attempt)

    def sync(self, photos: dict[str, Path], excluded: set[str], state_file: Path) -> SyncReport:
        """Index published photos not yet indexed (or changed); drop faces of photos no longer published
        or now excluded (minors). Never sends anything but the developed photo's bytes."""
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if state.get("collection") != self.collection_id:
            state = {"collection": self.collection_id, "photos": {}}
        indexed: dict[str, dict] = state["photos"]
        wanted = {pid: path for pid, path in photos.items() if pid not in excluded}
        report = SyncReport()

        def save() -> None:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=1, ensure_ascii=False))

        for pid in [p for p in indexed if p not in wanted or _signature(wanted[p]) != indexed[p]["source"]]:
            faces = indexed[pid]["faces"]
            try:
                for i in range(0, len(faces), 4096):
                    self._call("delete_faces", CollectionId=self.collection_id, FaceIds=faces[i:i + 4096])
            except Exception:
                report.failed.append(pid)
                continue
            del indexed[pid]
            report.removed += pid not in wanted
            save()
        for pid, path in wanted.items():
            if pid in indexed:
                continue
            try:
                response = self._call("index_faces", CollectionId=self.collection_id, Image={"Bytes": jpeg_bytes(path)},
                                      ExternalImageId=external_id(pid), MaxFaces=100, QualityFilter="AUTO")
            except Exception:
                report.failed.append(pid)
                continue
            indexed[pid] = {"external": external_id(pid), "source": _signature(path),
                            "faces": [r["Face"]["FaceId"] for r in response.get("FaceRecords", [])]}
            report.added += 1
            save()
        save()
        return report

    def counts(self, photos: dict[str, Path], cache_file: Path) -> dict[str, int]:
        """Faces Rekognition detects per photo, for the review; cached by file signature,
        so each photo costs one DetectFaces call until it changes."""
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        result = {}
        for key, path in photos.items():
            sig = _signature(path)
            if cache.get(key, {}).get("source") != sig:
                try:
                    found = self._call("detect_faces", Image={"Bytes": jpeg_bytes(path)}).get("FaceDetails", [])
                except Exception:
                    continue
                cache[key] = {"source": sig, "faces": len(found)}
            result[key] = cache[key]["faces"]
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
        return result


def _signature(path: Path) -> list:
    st = path.stat()
    return [st.st_size, int(st.st_mtime)]


# --- stack administration (enable / disable / purge / status) ------------------------------------

APP = Path(__file__).with_name("face_search_app.py")
DELETE_TARGET = "arn:aws:scheduler:::aws-sdk:rekognition:deleteCollection"
DELETE_HOUR = 3  # local time on the deletion day


class FaceStack:
    """The event's faces stack in sa-east-1: search function, deletion schedule and collection."""

    def __init__(self, outputs: dict[str, str], clients: dict, slug: str):
        self.outputs, self.clients, self.slug = outputs, clients, slug
        self.index = FaceIndex(outputs["CollectionId"], clients["rekognition"])

    @classmethod
    def load(cls, stack: str, profile: str, slug: str) -> FaceStack:
        import boto3
        session = boto3.Session(profile_name=profile, region_name=FACES_REGION)
        outputs = session.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
        clients = {name: session.client(name) for name in ("rekognition", "lambda", "scheduler")}
        return cls({o["OutputKey"]: o["OutputValue"] for o in outputs}, clients, slug)

    @property
    def schedule_name(self) -> str:
        return f"event-photos-{self.slug}-faces-delete"

    def deploy(self, threshold: float, enabled: bool = True, photo: bool = False) -> None:
        """Upload the search function and set its threshold and switches, keeping other settings."""
        fn = self.clients["lambda"]
        name = self.outputs["SearchFunctionName"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(APP, "index.py")
        fn.update_function_code(FunctionName=name, ZipFile=buf.getvalue())
        _wait_updated(fn, name)
        self.configure(threshold, enabled, photo)

    def configure(self, threshold: float, enabled: bool, photo: bool = False) -> None:
        fn = self.clients["lambda"]
        name = self.outputs["SearchFunctionName"]
        env = fn.get_function(FunctionName=name)["Configuration"].get("Environment", {}).get("Variables", {})
        env |= {"THRESHOLD": f"{threshold:g}", "ENABLED": "1" if enabled else "0", "PHOTO_OK": "1" if photo else "0"}
        fn.update_function_configuration(FunctionName=name, Environment={"Variables": env})
        _wait_updated(fn, name)

    def schedule_deletion(self, when: dt.datetime, timezone: str) -> None:
        """One-time schedule that deletes the collection, then removes itself."""
        spec = {"Name": self.schedule_name, "ScheduleExpression": f"at({when:%Y-%m-%dT%H:%M:%S})",
                "ScheduleExpressionTimezone": timezone, "FlexibleTimeWindow": {"Mode": "OFF"},
                "ActionAfterCompletion": "DELETE",
                "Target": {"Arn": DELETE_TARGET, "RoleArn": self.outputs["DeleteRoleArn"],
                           "Input": json.dumps({"CollectionId": self.outputs["CollectionId"]})}}
        scheduler = self.clients["scheduler"]
        try:
            scheduler.create_schedule(**spec)
        except Exception as exc:
            if error_code(exc) != "ConflictException":
                raise
            scheduler.update_schedule(**spec)

    def scheduled_for(self) -> str | None:
        try:
            return self.clients["scheduler"].get_schedule(Name=self.schedule_name)["ScheduleExpression"]
        except Exception as exc:
            if error_code(exc) == "ResourceNotFoundException":
                return None
            raise

    def purge(self) -> None:
        """Delete the collection and its schedule now."""
        for call in (lambda: self.clients["rekognition"].delete_collection(CollectionId=self.outputs["CollectionId"]),
                     lambda: self.clients["scheduler"].delete_schedule(Name=self.schedule_name)):
            try:
                call()
            except Exception as exc:
                if error_code(exc) != "ResourceNotFoundException":
                    raise

    def photo_on(self) -> bool:
        """Whether the deployed function takes photos from the phone."""
        config = self.clients["lambda"].get_function(FunctionName=self.outputs["SearchFunctionName"])["Configuration"]
        return config.get("Environment", {}).get("Variables", {}).get("PHOTO_OK") == "1"

    def face_count(self) -> int | None:
        try:
            return self.clients["rekognition"].describe_collection(
                CollectionId=self.outputs["CollectionId"])["FaceCount"]
        except Exception as exc:
            if error_code(exc) == "ResourceNotFoundException":
                return None
            raise


def _wait_updated(fn, name: str) -> None:
    """Lambda rejects a second update while the previous one is still being applied."""
    for _ in range(60):
        config = fn.get_function(FunctionName=name)["Configuration"]
        if config.get("LastUpdateStatus", "Successful") != "InProgress":
            return
        time.sleep(1)


def deletion_time(event_date: str, retention_days: int) -> dt.datetime:
    return dt.datetime.combine(dt.date.fromisoformat(event_date) + dt.timedelta(days=retention_days),
                               dt.time(DELETE_HOUR))


def missing_preconditions(event: dict, settings: FaceSearchConfig, ack: Path) -> list[str]:
    """What still blocks turning face search on: legal sign-off, removal contact, AI opt-out."""
    missing = []
    if not settings.stack:
        missing.append("face_search.stack com a stack da busca em sa-east-1")
    if not _is_date(settings.legal_ok):
        missing.append("face_search.legal_ok com a data do parecer jurídico por escrito (AAAA-MM-DD)")
    if not event.get("removal_contact"):
        missing.append("removal_contact com o e-mail para pedidos de remoção")
    if not ack.exists():
        missing.append("confirmação de que a política de opt-out de serviços de IA da AWS está ativa "
                       "(rode de novo com --confirm-ai-opt-out)")
    return missing
