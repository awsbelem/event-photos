import json

from PIL import Image

from event_photos.gallery import PHOTO_LIST, build_gallery


def run_dir(tmp_path, names=("a.jpg", "b.jpg")):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    for n in names:
        Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / n)
    rows = [{"name": n, "output": n, "keep": True, "capture_time": None} for n in names]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    return run


EVENT = {"name": "E", "date": "2026-10-31", "place": "P", "moments": []}


def test_the_photo_list_is_published_beside_the_page_with_the_same_photos(tmp_path):
    site = tmp_path / "site"
    html = build_gallery(run_dir(tmp_path), site, dict(EVENT)).read_text()
    listed = json.loads((site / PHOTO_LIST).read_text())
    assert [p["id"] for p in listed["photos"]] == ["a", "b"] and listed["at"]
    assert listed["moments"] == [{"t": "", "n": "Outros momentos"}]
    assert all(f'"id":"{p}"' in html for p in ("a", "b"))  # the page still carries its list: no extra request to open


def test_an_open_gallery_checks_for_new_photos_only_while_it_is_on_screen(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert f'fetch("{PHOTO_LIST}",{{cache:"no-cache"}})' in html and "visibilitychange" in html
    assert 'class="btn primary fresh"' in html and 'aria-live="polite"' in html.split('class="btn primary fresh"')[0][-200:]
    assert "fotos novas" in html and 'hit("new")' in html and "location.reload()" in html


def test_the_reload_goes_to_the_first_new_photo_and_marks_the_new_ones(tmp_path):
    html = build_gallery(run_dir(tmp_path), tmp_path / "site", dict(EVENT)).read_text()
    assert '"#novas="' in html and "/^#novas=(.+)$/" in html  # the new ids ride in the address across the reload
    assert "NEW.has(p.id)" in html and 'content:"Nova"' in html  # tiles built later are marked too
    assert 'history.scrollRestoration="manual"' in html and "#volta=" not in html
