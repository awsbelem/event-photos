import datetime as dt
import json

from PIL import Image

from event_photos.gallery import Moment, build_gallery


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


def test_tiles_are_built_in_batches_by_the_script(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert 'class="tile"' not in html.split("<script>")[0]  # no tile markup: a page of thousands stays small
    assert '<div class="grid"></div><div class="rest"></div>' in html and '"m":0' in html and '"w":' in html
    assert "layout(PHOTOS)" in html and "innerHTML" not in html  # alts carry names: DOM calls only


def test_moments_hang_on_the_timeline_with_their_time_and_keynotes_marked(tmp_path):
    run = run_dir(tmp_path)
    rows = [{"name": "a.jpg", "output": "a.jpg", "keep": True, "capture_time": "2026-10-31T09:20:00"}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    moments = [Moment(dt.time(9, 0), "Abertura"), Moment(dt.time(9, 10), "Keynote: Vanessa Santos")]
    html = build_gallery(run, tmp_path / "site", dict(EVENT, moments=moments, heading="Momentos do dia")).read_text()
    assert "<h1>Momentos do dia</h1>" in html and 'class="moment keynote" data-t="09:10"' in html
    assert "<time>09:10</time>" in html and '<span class="n">1 foto</span>' in html
    assert 'class="now before"' in html and 'href="#keynote-vanessa-santos"' in html  # the schedule jumps to it
    assert 'id="abertura" class="moment empty"' in html  # the whole schedule shows, photos or not


def test_page_carries_its_artwork_inline(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert "data:font/woff2;base64," in html and "data:image/svg+xml;base64," in html  # one file, no requests
    assert 'class="moment plain"' in html and 'class="now' not in html  # no schedule: no timeline, no bar


def framed_run(tmp_path):
    run = run_dir(tmp_path)
    metrics = json.loads((run / "metrics.json").read_text())
    metrics["stats"]["frames"] = [{"key": "x", "label": "X"}, {"key": "y", "label": "Y"}]
    (run / "metrics.json").write_text(json.dumps(metrics))
    return run


def test_a_phone_on_its_side_puts_the_photo_beside_the_controls(tmp_path):
    # Stacked, the controls left the photo 87 px of a 390 px tall screen.
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert "@media (orientation:landscape) and (max-height:540px)" in html


def test_visitors_pick_post_or_story_when_the_photo_has_frames(tmp_path):
    html = build_gallery(framed_run(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert 'aria-label="Formato"' in html
    assert 'data-format="feed"' in html and "Post (4:5)" in html
    assert 'data-format="story"' in html and "Story (9:16)" in html


def test_no_format_choice_without_frames(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert 'aria-label="Formato"' not in html
