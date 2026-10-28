import json

from PIL import Image

from event_photos.gallery import BEACON, build_gallery


def run_dir(tmp_path):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / "a.jpg")
    rows = [{"name": "a.jpg", "output": "a.jpg", "keep": True, "capture_time": None}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    return run


EVENT = {"name": "E", "date": "2026-10-31", "place": "P", "moments": [], "instagram": "@ev"}


def gallery(tmp_path, **extra):
    site = tmp_path / "site"
    return site, build_gallery(run_dir(tmp_path), site, dict(EVENT, **extra)).read_text()


def test_the_site_carries_a_tiny_gif_that_the_counts_are_requests_for(tmp_path):
    site, _ = gallery(tmp_path)
    data = (site / BEACON).read_bytes()
    assert data.startswith(b"GIF89a") and len(data) < 100


def test_each_counted_action_sends_its_event(tmp_path):
    _, html = gallery(tmp_path)
    for name in ("open", "photo", "frame", "save", "share", "tag"):
        assert f'hit("{name}"' in html, name
    assert f'fetch("{BEACON}?"' in html and "keepalive:true" in html  # survives the page closing right after


def test_counts_carry_no_visitor_identifier(tmp_path):
    _, html = gallery(tmp_path)
    assert "localStorage" not in html and "sessionStorage" not in html and "document.cookie" not in html


def test_face_search_counts_only_the_size_of_the_result(tmp_path):
    _, html = gallery(tmp_path, face_search_ui={"url": "https://u.example/", "ids": {}, "until": "30/11/2026"})
    assert 'hit("find"' in html and '"1-5"' in html and '"6+"' in html


def test_the_footer_says_what_is_counted(tmp_path):
    _, html = gallery(tmp_path)
    assert "sem identificar ninguém" in html.split("<footer>")[1]


def test_the_site_has_the_event_icon_for_the_tab_and_the_home_screen(tmp_path):
    site, html = gallery(tmp_path)
    with Image.open(site / "favicon.ico") as ico:
        assert ico.format == "ICO" and {(16, 16), (32, 32)} <= set(ico.info["sizes"])
    with Image.open(site / "apple-touch-icon.png") as touch:
        assert touch.size == (180, 180) and touch.mode == "RGB"  # iOS rounds it; a transparent corner turns black
    head = html.split("</head>")[0]
    assert '<link rel="icon" href="favicon.ico"' in head and '<link rel="apple-touch-icon" href="apple-touch-icon.png">' in head
