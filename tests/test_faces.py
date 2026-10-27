import json

import pytest
from PIL import Image

from event_photos.faces import FaceIndex, external_id


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeRekognition:
    def __init__(self, fail=None):
        self.faces = {}  # face id -> external id
        self.calls = []
        self.fail = fail or {}  # external id -> list of error codes to raise, in order

    def index_faces(self, CollectionId, Image, ExternalImageId, MaxFaces, QualityFilter):
        self.calls.append(("index", ExternalImageId))
        assert Image["Bytes"][:3] == b"\xff\xd8\xff"  # JPEG bytes, never an S3 reference
        if self.fail.get(ExternalImageId):
            raise ApiError(self.fail[ExternalImageId].pop(0))
        ids = [f"{ExternalImageId}-f{i}" for i in range(2)]
        self.faces.update({i: ExternalImageId for i in ids})
        return {"FaceRecords": [{"Face": {"FaceId": i}} for i in ids]}

    def delete_faces(self, CollectionId, FaceIds):
        self.calls.append(("delete", tuple(FaceIds)))
        for i in FaceIds:
            self.faces.pop(i, None)
        return {}


def photo(tmp_path, name, size=(3000, 2000)):
    path = tmp_path / f"{name}.jpg"
    Image.new("RGB", size, (120, 80, 60)).save(path)
    return path


def test_ids_rekognition_rejects_are_hashed_stably():
    assert external_id("ana-souza--IMG_1-ab12cd") == "ana-souza--IMG_1-ab12cd"
    assert external_id("foto com espaço") == external_id("foto com espaço") != "foto com espaço"
    assert external_id("foto com espaço").startswith("h-")


def test_sync_adds_removes_and_excludes(tmp_path):
    rek, state = FakeRekognition(), tmp_path / "face_index.json"
    a, b, c = photo(tmp_path, "a"), photo(tmp_path, "b"), photo(tmp_path, "c")
    index = FaceIndex("col", rek, sleep=lambda s: None)
    first = index.sync({"a": a, "b": b, "c": c}, excluded={"c"}, state_file=state)
    assert (first.added, first.removed, first.failed) == (2, 0, [])
    assert set(rek.faces.values()) == {"a", "b"}
    second = index.sync({"a": a}, excluded=set(), state_file=state)  # b unpublished
    assert (second.added, second.removed) == (0, 1) and set(rek.faces.values()) == {"a"}
    third = index.sync({"a": a}, excluded={"a"}, state_file=state)  # a marked as showing a minor
    assert third.removed == 1 and rek.faces == {}


def test_repeat_publish_indexes_nothing_new(tmp_path):
    rek, state = FakeRekognition(), tmp_path / "face_index.json"
    a = photo(tmp_path, "a")
    index = FaceIndex("col", rek, sleep=lambda s: None)
    index.sync({"a": a}, set(), state)
    rek.calls.clear()
    assert index.sync({"a": a}, set(), state).added == 0 and rek.calls == []


def test_throttling_is_retried_then_reported_and_retried_next_time(tmp_path):
    state, a = tmp_path / "face_index.json", photo(tmp_path, "a")
    rek = FakeRekognition(fail={"a": ["ThrottlingException"] * 5})
    sleeps = []
    report = FaceIndex("col", rek, sleep=sleeps.append).sync({"a": a}, set(), state)
    assert report.failed == ["a"] and len(sleeps) == 4
    assert FaceIndex("col", rek, sleep=sleeps.append).sync({"a": a}, set(), state).added == 1


def test_other_errors_fail_fast(tmp_path):
    rek = FakeRekognition(fail={"a": ["InvalidImageFormatException"]})
    sleeps = []
    report = FaceIndex("col", rek, sleep=sleeps.append).sync({"a": photo(tmp_path, "a")}, set(), tmp_path / "s.json")
    assert report.failed == ["a"] and sleeps == []


def test_state_is_saved_per_photo_and_bytes_are_bounded(tmp_path):
    rek, state = FakeRekognition(), tmp_path / "face_index.json"
    FaceIndex("col", rek, sleep=lambda s: None).sync({"big": photo(tmp_path, "big", (8000, 6000))}, set(), state)
    saved = json.loads(state.read_text())
    assert saved["collection"] == "col" and saved["photos"]["big"]["faces"] == ["big-f0", "big-f1"]


def test_changed_photo_is_reindexed(tmp_path):
    rek, state = FakeRekognition(), tmp_path / "face_index.json"
    a = photo(tmp_path, "a")
    index = FaceIndex("col", rek, sleep=lambda s: None)
    index.sync({"a": a}, set(), state)
    Image.new("RGB", (2000, 2000), (10, 10, 10)).save(a)  # redeveloped
    report = index.sync({"a": a}, set(), state)
    assert report.added == 1 and report.removed == 0 and ("delete", ("a-f0", "a-f1")) in rek.calls


def test_publish_sends_approved_photos_and_skips_minors(tmp_path):
    from event_photos.cli import published_photos
    rows = [{"name": "a.heic", "output": "a.jpg", "keep": True}, {"name": "b.jpg", "output": "b.jpg", "keep": False},
            {"name": "c.jpg", "output": "c.jpg", "keep": True}]
    (tmp_path / "metrics.json").write_text(json.dumps({"photos": rows}))
    (tmp_path / "review.json").write_text(json.dumps({"keep": {}, "minors": ["c.jpg"]}))
    photos, minors = published_photos(tmp_path)
    assert set(photos) == {"a", "c"} and photos["a"] == tmp_path / "selected" / "a.jpg" and minors == {"c"}


def test_publish_goes_on_when_face_search_fails(monkeypatch, tmp_path, capsys):
    from event_photos import cli
    monkeypatch.setattr(cli.FaceStack, "load", classmethod(lambda *a: (_ for _ in ()).throw(OSError("offline"))))
    assert cli._sync_faces({"face_search": {"enabled": True, "stack": "s"}}, tmp_path, "e") is None
    assert "Publicando sem a busca" in capsys.readouterr().out
    assert cli._sync_faces({}, tmp_path, "e") is None  # disabled: does nothing


def test_face_counts_are_cached_until_the_photo_changes(tmp_path):
    class Detect(FakeRekognition):
        def __init__(self):
            super().__init__()
            self.detects = 0

        def detect_faces(self, Image):
            self.detects += 1
            return {"FaceDetails": [{}, {}, {}]}

    rek, a = Detect(), photo(tmp_path, "a")
    index = FaceIndex("col", rek, sleep=lambda s: None)
    assert index.counts({"a.jpg": a}, tmp_path / "c.json") == {"a.jpg": 3}
    index.counts({"a.jpg": a}, tmp_path / "c.json")
    assert rek.detects == 1


def test_faces_are_counted_on_the_image_that_would_be_indexed(tmp_path):
    # The preview (1200 px) can miss a small face the developed photo (sent at 1920 px) shows.
    from event_photos.cli import face_images
    rows = [{"name": "a.jpg", "output": "a.jpg", "preview": "a.jpg", "keep": True},
            {"name": "b.jpg", "output": "b.jpg", "preview": "b.jpg", "keep": False}]
    (tmp_path / "metrics.json").write_text(json.dumps({"photos": rows}))
    for f in ("selected/a.jpg", "previews/after/a.jpg", "previews/after/b.jpg"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    assert face_images(tmp_path) == {"a.jpg": tmp_path / "selected/a.jpg", "b.jpg": tmp_path / "previews/after/b.jpg"}


def test_publish_leaves_photos_without_faces_out_of_the_index(monkeypatch, tmp_path):
    from event_photos import cli
    rows = [{"name": n, "output": n, "preview": n, "keep": True} for n in ("a.jpg", "b.jpg", "c.jpg", "d.jpg")]
    (tmp_path / "metrics.json").write_text(json.dumps({"photos": rows}))
    (tmp_path / "review.json").write_text(json.dumps({"keep": {}, "minors": ["c.jpg"]}))
    sent = {}

    class Index:
        def exists(self):
            return True

        def counts(self, photos, cache_file):
            return {"a.jpg": 0, "b.jpg": 2, "c.jpg": 1}  # d.jpg: not counted (Rekognition hiccup)

        def sync(self, photos, excluded, state_file):
            sent["excluded"] = excluded
            state_file.write_text(json.dumps({"photos": {}}))
            return type("R", (), {"summary": lambda self: ""})()

    stack = type("S", (), {"index": Index(), "outputs": {"SearchUrl": "u"}})()
    monkeypatch.setattr(cli.FaceStack, "load", classmethod(lambda *a: stack))
    assert cli._sync_faces({"date": "2026-10-31", "face_search": {"enabled": True, "stack": "s"}}, tmp_path, "e")
    assert sent["excluded"] == {"a", "c"}  # no faces, and the minor; an uncounted photo still goes
