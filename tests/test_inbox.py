import datetime as dt
import json

import pytest

from event_photos import inbox_app
from event_photos.gallery import owner_of, parse_offset
from event_photos.inbox import CODE_ALPHABET, Inbox, new_code, slugify, sync_links


class FakeS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, config):
        self.config = config

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(json.dumps(self.config).encode())}

    def generate_presigned_post(self, bucket, key, Fields, Conditions, ExpiresIn):
        return {"url": f"https://{bucket}.s3.amazonaws.com/", "fields": {"key": key}}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(inbox_app, "_s3", FakeS3({"ABCD-EFGH": {"slug": "ana", "name": "Ana"}}))
    monkeypatch.setattr(inbox_app, "BUCKET", "inbox")
    return lambda path, body: inbox_app.handler(
        {"requestContext": {"http": {"method": "POST"}}, "rawPath": path, "body": json.dumps(body)}, None)


def test_unknown_code_is_refused(app):
    assert app("/check", {"code": "ZZZZ-ZZZZ"})["statusCode"] == 403


def test_code_is_case_and_space_tolerant(app):
    reply = app("/check", {"code": " abcd-efgh "})
    assert reply["statusCode"] == 200 and json.loads(reply["body"])["name"] == "Ana"


def test_signed_form_lands_in_the_photographers_folder(app):
    reply = app("/sign", {"code": "ABCD-EFGH", "name": "IMG_0001.HEIC", "size": 3_000_000, "modified": 1})
    assert json.loads(reply["body"])["fields"]["key"].startswith("incoming/ana/IMG_0001-")


def test_retry_gets_the_same_key_but_same_name_other_photo_does_not():
    a, _ = inbox_app.upload_key("ana", "image.jpg", 100, 111)
    b, _ = inbox_app.upload_key("ana", "image.jpg", 100, 111)
    c, _ = inbox_app.upload_key("ana", "image.jpg", 120, 222)
    assert a == b != c


@pytest.mark.parametrize("name,size", [("video.mov", 10), ("IMG.jpg", 0), ("IMG.jpg", 300 * 1024 * 1024), ("x", 10)])
def test_bad_files_are_refused(name, size):
    assert inbox_app.upload_key("ana", name, size, 1)[1]


def test_page_is_served():
    reply = inbox_app.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/"}, None)
    assert reply["statusCode"] == 200 and "Enviar fotos" in reply["body"]


def test_codes_avoid_ambiguous_characters():
    code = new_code()
    assert len(code) == 9 and code[4] == "-" and set(code.replace("-", "")) <= set(CODE_ALPHABET)


def test_owner_and_clock_offset():
    assert slugify("João da Silva") == "joao-da-silva"
    assert owner_of("joao-da-silva--IMG_1-ab12cd") == "joao-da-silva" and owner_of("IMG_1") == ""
    assert parse_offset("-0:05") == -dt.timedelta(minutes=5) and parse_offset("1:30") == dt.timedelta(hours=1, minutes=30)


def test_review_notes_flag_what_the_reviewer_should_know(monkeypatch, tmp_path):
    from event_photos import cli
    dated = tmp_path / "uploads-dated" / "ana" / "a.jpg"
    original = tmp_path / "uploads" / "ana" / "b.heic"
    monkeypatch.setattr(cli, "read_capture_times", lambda ps: {dated: dt.datetime(2026, 10, 31, 9), original: dt.datetime(2026, 10, 21, 9)})
    monkeypatch.setattr(cli, "read_image_sizes", lambda ps: {dated: (1600, 1200), original: (4000, 3000)})
    notes = cli.review_notes({"ana--a.jpg": dated, "ana--b.heic": original}, dt.date(2026, 10, 31))
    assert [n.split(" ")[0] for n in notes["ana--a.jpg"]] == ["Horário", "Baixa"]
    assert notes["ana--b.heic"] == ["Tirada em 21/10, fora do dia do evento"]


def test_sync_links_creates_and_prunes(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    for n in ("ana--IMG_1.jpg", "ana--IMG_2.jpg"):
        (uploads / n).write_bytes(b"x")
    inbox = tmp_path / "inbox"
    links = sync_links({n: uploads / n for n in ("ana--IMG_1.jpg", "ana--IMG_2.jpg")}, inbox)
    assert [p.name for p in links] == ["ana--IMG_1.jpg", "ana--IMG_2.jpg"]
    sync_links({"ana--IMG_1.jpg": uploads / "ana--IMG_1.jpg"}, inbox)
    assert sorted(p.name for p in inbox.iterdir()) == ["ana--IMG_1.jpg"]


class MemoryInbox(Inbox):
    """Inbox with the S3 config kept in memory; counts writes."""

    def __init__(self, config=None):
        self.config, self.writes = dict(config or {}), 0

    def photographers(self):
        return dict(self.config)

    def save(self, config):
        self.config, self.writes = dict(config), self.writes + 1


def test_add_many_skips_known_names_and_dedupes_slugs():
    box = MemoryInbox({"AAAA-BBBB": {"slug": "ana-souza", "name": "Ana Souza"}})
    added = box.add_many(["Ana Souza", "Maria Silva", "", " Maria  Silva ", "Maria Sílva"])
    assert [(n, s) for n, _, s in added] == [("Maria Silva", "maria-silva"), ("Maria Sílva", "maria-silva-2")]
    assert box.writes == 1 and len(box.config) == 3


def test_copy_from_keeps_the_same_codes_and_existing_ones():
    official = MemoryInbox({"AAAA-BBBB": {"slug": "ana", "name": "Ana"}, "CCCC-DDDD": {"slug": "bia", "name": "Bia"}})
    training = MemoryInbox({"CCCC-DDDD": {"slug": "bia", "name": "Bia"}})
    assert training.copy_from(official) == 1
    assert training.config == official.config
    assert training.copy_from(official) == 0 and training.writes == 1


def test_page_names_the_event(monkeypatch):
    assert "<h1>Enviar fotos do evento</h1>" in inbox_app.page()
    monkeypatch.setattr(inbox_app, "EVENT_NAME", "Treino <equipe>")
    html = inbox_app.page()
    assert "Treino &lt;equipe&gt;" in html and "__" not in html


def test_deployed_source_carries_the_event_name():
    from event_photos.inbox import app_source
    namespace = {}
    exec(compile(app_source("Jantar — AWS"), "index.py", "exec"), namespace)
    assert namespace["EVENT_NAME"] == "Jantar — AWS"
