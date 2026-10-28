import json

from PIL import Image

from event_photos.gallery import PHOTO_LIST, build_gallery
from event_photos.publish import REVALIDATE, aws_commands
from event_photos.wall import WALL


def run_dir(tmp_path):
    run = tmp_path / "run"
    (run / "selected").mkdir(parents=True)
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(run / "selected" / "a.jpg")
    rows = [{"name": "a.jpg", "output": "a.jpg", "keep": True, "capture_time": "2026-10-31T10:32:00"}]
    (run / "metrics.json").write_text(json.dumps({"stats": {}, "photos": rows}))
    return run


EVENT = {"name": "E", "date": "2026-10-31", "place": "P", "moments": [], "instagram": "@ev"}


def wall(tmp_path, **extra):
    site = tmp_path / "site"
    build_gallery(run_dir(tmp_path), site, dict(EVENT, **extra))
    return site, (site / WALL).read_text()


def test_the_wall_is_built_beside_the_gallery_in_the_event_artwork(tmp_path):
    _, html = wall(tmp_path)
    assert 'name="robots" content="noindex,nofollow"' in html and 'lang="pt-BR"' in html
    assert 'class="hex hex-l"' in html and 'class="hex hex-r"' in html and 'class="skyline"' in html
    assert "data:image/svg+xml;base64," in html  # the logo, inlined like every asset
    assert 'src="http' not in html and "url(http" not in html  # nothing from another host


def test_the_wall_follows_the_published_list_and_counts_its_hours(tmp_path):
    _, html = wall(tmp_path)
    assert f'fetch("{PHOTO_LIST}",{{cache:"no-cache"}})' in html and 'hit("wall")' in html
    assert "view/" in html and "Ache suas fotos" in html and "As fotos do dia aparecem aqui" in html


def test_the_qr_leads_to_the_gallery_when_its_address_is_known(tmp_path):
    _, html = wall(tmp_path, url="https://d123.cloudfront.net")
    assert '<svg' in html.split('class="qr"')[1][:200]
    _, html = wall(tmp_path / "x")
    assert 'class="qr"' not in html  # a local build has no public address to point at


def test_each_photo_carries_its_own_time_for_the_wall(tmp_path):
    site, _ = wall(tmp_path)
    listed = json.loads((site / PHOTO_LIST).read_text())
    assert listed["photos"][0]["t"] == "10:32"


def test_the_wall_goes_up_with_the_pages(tmp_path):
    site, _ = wall(tmp_path)
    cmds = [" ".join(c) for c in aws_commands(site, "b", "D1")]
    assert any(c.endswith(f"s3://b/{WALL} --cache-control {REVALIDATE}") for c in cmds)


def test_a_short_link_takes_the_place_of_the_gallery_address(tmp_path):
    _, html = wall(tmp_path, url="https://d123.cloudfront.net", short_url="https://cdnorte.link/fotos")
    assert "cdnorte.link/fotos" in html and "d123.cloudfront.net" not in html
