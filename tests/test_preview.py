import datetime as dt
import json
from pathlib import Path

from PIL import Image

from event_photos.gallery import GalleryPhoto, _showcase, build_gallery
from event_photos.preview import CARD, CARD_DIR, HOME_CARD, PAGE_DIR
from event_photos.publish import IMMUTABLE, REVALIDATE, aws_commands

URL = "https://d123.cloudfront.net"
EVENT = {"name": "Evento X", "date": "2026-10-31", "place": "Belém", "moments": []}
FACE = {"faces": [{"box": [.4, .2, .6, .5]}]}


def gallery(tmp_path, **extra):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    rows = []
    for i, size in enumerate(((1200, 800), (800, 1200))):
        Image.new("RGB", size, (90, 90 + i * 40, 90)).save(run / "selected" / f"p{i}.jpg")
        rows.append({"name": f"p{i}.jpg", "output": f"p{i}.jpg", "keep": True, "score": 1.0 + i,
                     "capture_time": f"2026-10-31T10:3{i}:00", "analysis": FACE})
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    site = tmp_path / "site"
    build_gallery(run, site, dict(EVENT, **extra))
    return site


def test_the_gallery_link_shows_the_event_and_a_card_of_its_photos(tmp_path):
    site = gallery(tmp_path, url=URL + "/")
    html = (site / "index.html").read_text()
    assert f'property="og:url" content="{URL}/"' in html and 'property="og:title" content="Evento X"' in html
    assert f'property="og:image" content="{URL}/{HOME_CARD}?v=' in html
    assert 'property="og:description" content="31 de outubro de 2026 · Belém"' in html  # no count to go stale
    assert 'name="twitter:card" content="summary_large_image"' in html
    with Image.open(site / HOME_CARD) as card:
        assert card.size == CARD
    assert (site / HOME_CARD).stat().st_size < 300_000


def test_each_photo_has_a_page_whose_preview_is_that_photo(tmp_path):
    site = gallery(tmp_path, url=URL)
    page = (site / PAGE_DIR / "p0.html").read_text()
    assert f'property="og:image" content="{URL}/{CARD_DIR}/p0.jpg"' in page
    assert f'property="og:url" content="{URL}/{PAGE_DIR}/p0.html"' in page
    assert 'property="og:image:alt" content="Foto do evento · 10:30"' in page
    assert 'location.replace("../#foto=p0")' in page and "http-equiv" not in page  # crawlers stay on this page
    with Image.open(site / CARD_DIR / "p0.jpg") as card:
        assert card.size == CARD
    assert (site / CARD_DIR / "p0.jpg").stat().st_size < 150_000


def test_without_a_public_address_no_preview_image_is_promised(tmp_path):
    site = gallery(tmp_path)
    assert "og:image" not in (site / "index.html").read_text()
    assert "og:image" not in (site / PAGE_DIR / "p0.html").read_text()


def test_the_preview_apps_may_read_the_site_but_search_engines_may_not(tmp_path):
    robots = (gallery(tmp_path) / "robots.txt").read_text()
    assert "User-agent: LinkedInBot" in robots and robots.rstrip().endswith("User-agent: *\nDisallow: /")


def test_the_viewer_sends_the_photo_page_not_the_gallery(tmp_path):
    html = (gallery(tmp_path) / "index.html").read_text()
    assert "Enviar link da foto" in html and f'new URL("{PAGE_DIR}/"+encodeURIComponent(p.id)' in html
    assert 'hit("link"' in html
    assert 'querySelector(".copy-tag[data-tag]")' in html  # the @ button keeps its own copy action


def test_the_showcase_takes_the_best_photo_of_each_part_of_the_day():
    def photo(hour, score, w=1200):
        return GalleryPhoto(f"{hour}-{score}", Path("x"), dt.datetime(2026, 10, 31, hour), w, 800, score=score,
                            focus=(.5, .3))
    photos = [photo(9, 1), photo(9, 5), photo(12, 2), photo(13, 3), photo(17, 4), photo(18, 1), photo(10, 9, w=600)]
    assert [p.id for p in _showcase(photos)] == ["9-5", "17-4", "13-3"]  # the portrait one stays out


def test_cards_and_photo_pages_go_up_before_the_gallery(tmp_path):
    site = gallery(tmp_path, url=URL)
    cmds = [" ".join(c) for c in aws_commands(site, "b", "D1")]
    index = next(i for i, c in enumerate(cmds) if "s3://b/index.html" in c)
    assert any(f"s3://b/{CARD_DIR} --cache-control {IMMUTABLE}" in c for c in cmds[:index])
    assert any(c.endswith(f"s3://b/{HOME_CARD} --cache-control {REVALIDATE}") for c in cmds[:index])
    assert any(f"s3://b/{PAGE_DIR} --cache-control {REVALIDATE}" in c for c in cmds[:index])
