import base64
import io
import json
import logging

import pytest
from PIL import Image

from event_photos import face_search_app as app


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeRekognition:
    def __init__(self, faces=1, matches=("a", "a", "b"), error=None, detect_error=None):
        self.n_faces, self.matches, self.error, self.detect_error = faces, matches, error, detect_error

    def detect_faces(self, Image):
        if self.detect_error:
            raise self.detect_error
        return {"FaceDetails": [{}] * self.n_faces}

    def search_faces_by_image(self, CollectionId, Image, FaceMatchThreshold, MaxFaces, QualityFilter):
        assert FaceMatchThreshold == app.THRESHOLD
        if self.error:
            raise ApiError(self.error)
        return {"FaceMatches": [{"Face": {"ExternalImageId": m}} for m in self.matches]}


class FakeDynamo:
    def __init__(self):
        self.counts = {}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues,
                    ReturnValues):
        k = Key["k"]["S"]
        self.counts[k] = self.counts.get(k, 0) + 1
        return {"Attributes": {"n": {"N": str(self.counts[k])}}}


def selfie() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 150, 120)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


SELFIE = selfie()


@pytest.fixture
def clients(monkeypatch):
    found = {"rekognition": FakeRekognition(), "dynamodb": FakeDynamo()}
    monkeypatch.setattr(app, "_clients", found)
    return found


def call(body, ip="203.0.113.7", path="/search", method="POST"):
    event = {"requestContext": {"http": {"method": method, "sourceIp": ip}}, "rawPath": path,
             "body": json.dumps(body) if isinstance(body, dict) else body}
    reply = app.handler(event, None)
    return reply["statusCode"], json.loads(reply["body"])


def test_returns_unique_photo_ids(clients):
    assert call({"consent": True, "image": SELFIE}) == (200, {"photos": ["a", "b"]})


def test_consent_is_required(clients):
    assert call({"consent": False, "image": SELFIE})[1]["error"] == app.NO_CONSENT
    assert call({"image": SELFIE})[0] == 400


@pytest.mark.parametrize("image", [base64.b64encode(b"\x89PNG....").decode(), "not base64!!"])
def test_only_jpeg(clients, image):
    assert call({"consent": True, "image": image}) == (400, {"error": app.NOT_JPEG})


def test_size_limits(clients):
    big = base64.b64encode(b"\xff\xd8\xff" + b"0" * (app.MAX_IMAGE + 1)).decode()
    assert call({"consent": True, "image": big}) == (400, {"error": app.TOO_BIG})
    assert call("x" * (app.MAX_BODY + 1)) == (400, {"error": app.TOO_BIG})


def test_no_face_many_faces_and_no_match(clients):
    clients["rekognition"] = FakeRekognition(faces=0)
    assert call({"consent": True, "image": SELFIE}) == (400, {"error": app.NO_FACE})
    clients["rekognition"] = FakeRekognition(faces=3)
    assert call({"consent": True, "image": SELFIE})[1]["note"] == app.MANY_FACES
    clients["rekognition"] = FakeRekognition(matches=())
    assert call({"consent": True, "image": SELFIE}) == (200, {"photos": [], "message": app.NO_MATCH})


def test_closed_collection_and_throttling(clients):
    clients["rekognition"] = FakeRekognition(error="ResourceNotFoundException")
    assert call({"consent": True, "image": SELFIE}) == (410, {"error": app.CLOSED})
    clients["rekognition"] = FakeRekognition(error="ThrottlingException")
    assert call({"consent": True, "image": SELFIE}) == (503, {"error": app.BUSY})


def test_rate_limit_per_minute_and_per_hour(clients, monkeypatch):
    for _ in range(5):
        assert call({"consent": True, "image": SELFIE})[0] == 200
    assert call({"consent": True, "image": SELFIE}) == (429, {"error": app.TOO_MANY})
    assert call({"consent": True, "image": SELFIE}, ip="198.51.100.1")[0] == 200  # someone else
    t = [3600 * 300.0]
    monkeypatch.setattr(app.time, "time", lambda: t[0])
    clients["dynamodb"] = FakeDynamo()
    statuses = []
    for i in range(31):
        t[0] = 3600 * 300.0 + i * 61  # a new minute each time, all within one hour
        statuses.append(call({"consent": True, "image": SELFIE}, ip="192.0.2.9")[0])
    assert statuses[:30] == [200] * 30 and statuses[30] == 429


def test_ip_is_never_stored_in_clear(clients):
    call({"consent": True, "image": SELFIE})
    assert all("203.0.113.7" not in k for k in clients["dynamodb"].counts)


def test_only_post_to_search(clients):
    assert call({}, method="GET")[0] == 404 and call({}, path="/other")[0] == 404


def test_selfie_never_reaches_the_logs(clients, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    clients["rekognition"] = FakeRekognition(detect_error=RuntimeError("boom"))
    assert call({"consent": True, "image": SELFIE}) == (503, {"error": app.BUSY})
    logged = capsys.readouterr().out + capsys.readouterr().err + caplog.text
    assert "RuntimeError" in logged and SELFIE[:40] not in logged and SELFIE[-40:] not in logged


def test_disabled_function_answers_nothing(clients, monkeypatch):
    monkeypatch.setattr(app, "ENABLED", False)
    assert call({"consent": True, "image": SELFIE}) == (410, {"error": app.DISABLED})


def test_one_ipv6_prefix_is_one_caller(clients):
    for i in range(5):
        assert call({"consent": True, "image": SELFIE}, ip=f"2001:db8:1:2::{i + 1}")[0] == 200
    assert call({"consent": True, "image": SELFIE}, ip="2001:db8:1:2:ffff::9")[0] == 429  # same /64
    assert call({"consent": True, "image": SELFIE}, ip="2001:db8:1:3::1")[0] == 200  # another /64


def test_global_cap_stops_everyone(clients, monkeypatch):
    monkeypatch.setattr(app, "GLOBAL_LIMIT", 3)
    statuses = [call({"consent": True, "image": SELFIE}, ip=f"198.51.100.{i}")[0] for i in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_replies_cannot_be_framed(clients):
    event = {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/"}
    headers = app.handler(event, None)["headers"]
    assert headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in headers["content-security-policy"]
