import json

from PIL import Image

from event_photos.fun import STICKERS, belem_png, logo_png, moment_group
from event_photos.gallery import PHOTO_LIST, build_gallery, load_event


def gallery(tmp_path, schedule=()):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / "a.jpg")
    rows = [{"name": "a.jpg", "output": "a.jpg", "keep": True, "capture_time": "2026-10-31T09:30:00",
             "analysis": {"faces": [{"box": [.4012, .2, .5, .35]}]}}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"name": "E", "date": "2026-10-31", "schedule": list(schedule)}))
    site = tmp_path / "site"
    build_gallery(run, site, load_event(event))
    return site


def test_schedule_titles_pick_their_stickers():
    assert moment_group("Credenciamento") == "arrive"
    assert moment_group("Keynote: Vanessa Santos") == "learn"
    assert moment_group("Café da manhã") == "pause" and moment_group("Intervalo para almoço") == "pause"
    assert moment_group("Encerramento") == "close"
    assert moment_group("Outros momentos") == ""  # general stickers


def test_no_sticker_talks_about_how_someone_looks():
    texts = [t for group in (*STICKERS["moments"].values(), *STICKERS["faces"].values(),
                             STICKERS["para"], STICKERS["community"]) for t in group]
    assert texts and not any(w in t.lower() for t in texts for w in ("bocão", "soninho", "careca", "feio", "dormi"))
    assert all("♥" not in t and "✓" not in t for t in texts)  # glyphs the page's Inter subset lacks


def test_the_page_knows_where_the_faces_are_and_which_moment_it_is(tmp_path):
    site = gallery(tmp_path, [{"time": "09:00", "title": "Keynote: X"}])
    listed = json.loads((site / PHOTO_LIST).read_text())
    assert listed["photos"][0]["x"] == [[0.4, 0.2, 0.5, 0.35]]
    assert listed["moments"][0]["g"] == "learn"


def test_the_fun_version_is_offered_even_without_frames(tmp_path):
    html = (gallery(tmp_path) / "index.html").read_text()
    assert 'data-mode="fun"' in html and "Divertida" in html and "Trocar stickers" in html
    assert 'hit("reroll"' in html and "const FUN=" in html
    assert 'data-mode="photo" aria-pressed="true">Foto' in html  # no frames: the photo is the default
    assert '"date": "31 de outubro de 2026"' in html  # written on the band under the photo
    assert 'querySelector(".skyline")' in html and 'class="skyline"' in html  # the band borrows the footer's skyline


def test_the_band_artwork_is_png_so_the_canvas_can_be_saved():
    assert logo_png().startswith("data:image/png;base64,") and belem_png().startswith("data:image/png;base64,")
