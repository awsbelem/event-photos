import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from event_photos import review as review_mod
from event_photos.review import load_minors, load_review, review

TOKEN = "t0ken"


@pytest.fixture(autouse=True)
def fixed_token(monkeypatch):
    monkeypatch.setattr(review_mod, "new_token", lambda: TOKEN)


def run_dir_with(tmp_path, names=("a.jpg", "b.jpg")):
    rows = [{"name": n, "output": n, "keep": True, "auto_keep": True, "reasons": [], "flags": [],
             "adjustments": None, "capture_time": None} for n in names]
    (tmp_path / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    return tmp_path


def test_older_flat_review_file_still_loads(tmp_path):
    (tmp_path / "review.json").write_text(json.dumps({"a.jpg": False}))
    assert load_review(tmp_path) == {"a.jpg": False} and load_minors(tmp_path) == set()


def approve(run, payload, port, **kw):
    out = {}
    t = threading.Thread(target=lambda: out.update(r=review(run, "T", port=port, open_browser=False, **kw)))
    t.start()
    for _ in range(50):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/{TOKEN}/approve", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req)
            break
        except OSError:
            time.sleep(0.05)
    t.join(5)
    return out["r"]


def test_minors_persist_and_page_offers_the_mark(tmp_path):
    run = run_dir_with(tmp_path)
    overrides = approve(run, {"keep": {"a.jpg": True, "b.jpg": False}, "minors": ["a.jpg", "zzz"]}, 8791,
                        ask_minors=True)
    assert overrides == {"b.jpg": False}
    assert load_minors(run) == {"a.jpg"}  # unknown names are dropped
    assert "Tem menor de idade" in (run / "review.html").read_text()


def test_minors_are_kept_when_the_mark_is_not_offered(tmp_path):
    run = run_dir_with(tmp_path)
    (run / "review.json").write_text(json.dumps({"keep": {}, "minors": ["a.jpg"]}))
    approve(run, {"keep": {"a.jpg": True, "b.jpg": True}}, 8792)
    assert load_minors(run) == {"a.jpg"} and "Tem menor" not in (run / "review.html").read_text()


def test_review_shows_face_counts(tmp_path):
    run = run_dir_with(tmp_path)
    approve(run, {"keep": {"a.jpg": True, "b.jpg": True}}, 8793, ask_minors=True, face_counts={"a.jpg": 1, "b.jpg": 4})
    html = (run / "review.html").read_text()
    assert "1 rosto<" in html and "4 rostos" in html


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serving(run, port):
    """The review running in the background; send() makes one request and returns its status."""
    t = threading.Thread(target=lambda: review(run, "T", port=port, open_browser=False), daemon=True)
    t.start()

    def send(path, data=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers or {},
                                     method="POST" if data is not None else "GET")
        for _ in range(50):
            try:
                return urllib.request.urlopen(req).status
            except urllib.error.HTTPError as e:
                return e.code
            except OSError:
                time.sleep(0.05)
        raise AssertionError("review server never came up")
    return send


def test_page_is_only_served_under_the_token_to_loopback_hosts(tmp_path):
    port = free_port()
    send = serving(run_dir_with(tmp_path), port)
    assert send(f"/{TOKEN}/review.html") == 200
    assert send("/review.html") == 404 and send("/metrics.json") == 404
    assert send(f"/{TOKEN}/review.html", headers={"Host": f"attacker.example:{port}"}) == 403  # DNS rebinding
    send(f"/{TOKEN}/approve", json.dumps({"keep": {}}).encode(), {"Content-Type": "application/json"})


def test_approve_rejects_what_another_site_could_send(tmp_path):
    send = serving(run_dir_with(tmp_path), free_port())
    payload = json.dumps({"keep": {}, "minors": []}).encode()
    assert send("/approve", payload, {"Content-Type": "application/json"}) == 404  # no token
    assert send(f"/{TOKEN}/approve", payload, {"Content-Type": "text/plain"}) == 415  # no-cors fetch / form
    assert send(f"/{TOKEN}/approve", b"not json", {"Content-Type": "application/json"}) == 400
    assert not (tmp_path / "review.json").exists()
    assert send(f"/{TOKEN}/approve", payload, {"Content-Type": "application/json"}) == 204
