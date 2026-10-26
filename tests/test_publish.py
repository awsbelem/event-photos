from pathlib import Path

from event_photos.publish import IMMUTABLE, REVALIDATE, aws_commands


def site(tmp_path: Path) -> Path:
    for folder in ("thumbs", "view", "photos", "feed", "story"):
        (tmp_path / folder).mkdir()
    for page in ("index.html", "robots.txt", "_headers"):
        (tmp_path / page).write_text("")
    return tmp_path


def test_photos_go_up_before_the_page_that_shows_them(tmp_path):
    cmds = [" ".join(c) for c in aws_commands(site(tmp_path), "b", "D1")]
    index = next(i for i, c in enumerate(cmds) if c.endswith("s3://b/index.html --cache-control " + REVALIDATE))
    photo_syncs = [i for i, c in enumerate(cmds) if IMMUTABLE in c]
    assert len(photo_syncs) == 5 and max(photo_syncs) < index


def test_leftovers_are_deleted_only_after_the_new_page_is_live(tmp_path):
    cmds = aws_commands(site(tmp_path), "b", "D1")
    delete = next(i for i, c in enumerate(cmds) if "--delete" in c)
    index = next(i for i, c in enumerate(cmds) if "s3://b/index.html" in c)
    assert delete > index
    assert "_headers" in cmds[delete]  # Cloudflare-only file, never uploaded to S3


def test_cache_is_cleared_last_with_the_chosen_profile(tmp_path):
    cmds = aws_commands(site(tmp_path), "b", "D1", profile="p")
    assert cmds[-1][3:5] == ["cloudfront", "create-invalidation"] and "D1" in cmds[-1]
    assert all(c[:3] == ["aws", "--profile", "p"] for c in cmds)
