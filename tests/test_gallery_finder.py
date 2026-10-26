import json

from PIL import Image

from event_photos.gallery import build_gallery


def run_dir(tmp_path):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / "a.jpg")
    rows = [{"name": "a.jpg", "output": "a.jpg", "keep": True, "capture_time": None}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    return run


EVENT = {"name": "E", "date": "2026-10-31", "place": "P", "moments": [], "removal_contact": "x@y.z"}


def test_no_search_ui_unless_the_publish_enabled_it(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert "Encontrar minhas fotos" not in html and "FINDER=null" in html and "getUserMedia" not in html


def test_search_ui_has_consent_gate_and_live_camera_only(tmp_path):
    event = dict(EVENT, face_search_ui={"url": "https://u.example/", "ids": {"h-1": "a"}, "until": "30/11/2026"})
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", event).read_text()
    assert 'class="btn primary find-me"' in html and "A selfie não é guardada" in html
    assert 'class="btn primary open-cam" disabled' in html  # camera stays closed until consent
    assert "getUserMedia" in html and 'type="file"' not in html  # no picking a photo from the phone
    assert "30/11/2026" in html and "x@y.z" in html and '"h-1": "a"' in html


def test_names_cannot_end_the_script_block_and_pages_cannot_be_framed(tmp_path):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / "x--a.jpg")
    rows = [{"name": "x--a.jpg", "output": "x--a.jpg", "keep": True, "capture_time": None}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    event = dict(EVENT, photographers={"x": "</script><img src=x onerror=alert(1)>", "y": "Y"})
    site = tmp_path / "site"
    html = build_gallery(run, site, event).read_text()
    assert html.count("</script>") == 1 and "\\u003c/script>" in html  # the block ends only where we end it
    headers = (site / "_headers").read_text()
    assert "X-Frame-Options: DENY" in headers and "frame-ancestors 'none'" in headers
