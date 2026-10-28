import json

import pytest

from event_photos.faces import FaceSearchConfig, face_search_config


def test_off_by_default():
    assert face_search_config({}) == FaceSearchConfig()
    assert face_search_config({"face_search": {"stack": "s"}}).enabled is False


def test_values_are_read():
    c = face_search_config({"face_search": {"enabled": True, "stack": "s", "threshold": 97, "retention_days": 15,
                                            "legal_ok": "2026-10-29"}})
    assert (c.enabled, c.stack, c.threshold, c.retention_days, c.legal_ok) == (True, "s", 97.0, 15, "2026-10-29")


@pytest.mark.parametrize("raw", [{"threshold": 70}, {"threshold": 100}, {"retention_days": 0},
                                 {"retention_days": 120}, {"enabled": True}])
def test_invalid_settings_stop_with_a_message(raw):
    with pytest.raises(SystemExit):
        face_search_config({"face_search": raw})


def test_local_file_overrides_and_merges_face_search(tmp_path):
    from event_photos.gallery import load_event
    (tmp_path / "event.json").write_text(json.dumps({
        "name": "E", "date": "2026-10-31", "removal_contact": "",
        "face_search": {"enabled": False, "stack": "s", "legal_ok": "2026-10-25"}}))
    (tmp_path / "event.local.json").write_text(json.dumps({"removal_contact": "a@b.c", "face_search": {"enabled": True}}))
    event = load_event(tmp_path / "event.json")
    assert event["removal_contact"] == "a@b.c"
    assert event["face_search"] == {"enabled": True, "stack": "s", "legal_ok": "2026-10-25"}


def test_photo_from_the_phone_is_off_without_its_own_sign_off():
    assert face_search_config({"face_search": {"legal_ok": "2026-10-25"}}).photo is False
    c = face_search_config({"face_search": {"legal_ok": "2026-10-25", "photo_ok": "2026-10-28"}})
    assert c.photo and c.photo_ok == "2026-10-28"


@pytest.mark.parametrize("raw", [{"photo_ok": "2026-10-28"}, {"legal_ok": "sim", "photo_ok": "2026-10-28"},
                                 {"legal_ok": "2026-10-25", "photo_ok": "sim"}])
def test_photo_ok_needs_both_dates(raw):
    with pytest.raises(SystemExit, match="photo_ok"):
        face_search_config({"face_search": raw})
