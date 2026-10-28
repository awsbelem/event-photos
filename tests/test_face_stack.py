import argparse
import datetime as dt
import json

import pytest

from event_photos import cli
from event_photos.faces import FaceSearchConfig, FaceStack, deletion_time, missing_preconditions


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeLambda:
    def __init__(self):
        self.env = {"COLLECTION_ID": "event-photos-x", "RATE_TABLE": "t"}
        self.code = None

    def update_function_code(self, FunctionName, ZipFile):
        self.code = ZipFile

    def get_function(self, FunctionName):
        return {"Configuration": {"Environment": {"Variables": dict(self.env)}, "LastUpdateStatus": "Successful"}}

    def update_function_configuration(self, FunctionName, Environment):
        self.env = Environment["Variables"]


class FakeScheduler:
    def __init__(self):
        self.schedules = {}

    def create_schedule(self, **spec):
        if spec["Name"] in self.schedules:
            raise ApiError("ConflictException")
        self.schedules[spec["Name"]] = spec

    def update_schedule(self, **spec):
        self.schedules[spec["Name"]] = spec

    def delete_schedule(self, Name):
        if Name not in self.schedules:
            raise ApiError("ResourceNotFoundException")
        del self.schedules[Name]

    def get_schedule(self, Name):
        if Name not in self.schedules:
            raise ApiError("ResourceNotFoundException")
        return self.schedules[Name]


class FakeRekognition:
    def __init__(self, exists=True):
        self.exists = exists

    def describe_collection(self, CollectionId):
        if not self.exists:
            raise ApiError("ResourceNotFoundException")
        return {"FaceCount": 7}

    def create_collection(self, CollectionId):
        self.exists = True

    def delete_collection(self, CollectionId):
        if not self.exists:
            raise ApiError("ResourceNotFoundException")
        self.exists = False


OUTPUTS = {"CollectionId": "event-photos-x", "SearchFunctionName": "fn", "DeleteRoleArn": "arn:role",
           "SearchUrl": "https://u.lambda-url.sa-east-1.on.aws/"}


def stack(rek_exists=True):
    return FaceStack(OUTPUTS, {"rekognition": FakeRekognition(rek_exists), "lambda": FakeLambda(),
                               "scheduler": FakeScheduler()}, "x")


def test_deploy_ships_the_app_and_keeps_other_settings():
    s = stack()
    s.deploy(97, enabled=True)
    env = s.clients["lambda"].env
    assert s.clients["lambda"].code[:2] == b"PK" and env["THRESHOLD"] == "97" and env["ENABLED"] == "1"
    assert env["COLLECTION_ID"] == "event-photos-x"
    s.configure(97, enabled=False)
    assert s.clients["lambda"].env["ENABLED"] == "0"


def test_the_photo_switch_follows_photo_ok():
    s = stack()
    s.deploy(95, enabled=True)
    assert s.clients["lambda"].env["PHOTO_OK"] == "0" and not s.photo_on()
    s.deploy(95, enabled=True, photo=True)
    assert s.clients["lambda"].env["PHOTO_OK"] == "1" and s.photo_on()


def test_deletion_is_scheduled_once_and_rescheduling_updates_it():
    s = stack()
    s.schedule_deletion(dt.datetime(2026, 11, 30, 3), "America/Belem")
    s.schedule_deletion(dt.datetime(2026, 12, 15, 3), "America/Belem")
    spec = s.clients["scheduler"].schedules["event-photos-x-faces-delete"]
    assert spec["ScheduleExpression"] == "at(2026-12-15T03:00:00)" and spec["ActionAfterCompletion"] == "DELETE"
    assert json.loads(spec["Target"]["Input"]) == {"CollectionId": "event-photos-x"}
    assert s.scheduled_for() == "at(2026-12-15T03:00:00)"


def test_purge_twice_is_harmless():
    s = stack()
    s.schedule_deletion(dt.datetime(2026, 11, 30, 3), "America/Belem")
    s.purge()
    s.purge()
    assert s.face_count() is None and s.scheduled_for() is None


def test_deletion_time_is_event_date_plus_retention():
    assert deletion_time("2026-10-31", 30) == dt.datetime(2026, 11, 30, 3)


def test_preconditions_name_what_is_missing(tmp_path):
    ack = tmp_path / "ack.json"
    missing = missing_preconditions({}, FaceSearchConfig(stack="s"), ack)
    assert len(missing) == 3 and any("parecer" in m for m in missing) and any("opt-out" in m for m in missing)
    ack.write_text("{}")
    assert missing_preconditions({"removal_contact": "a@b.c"}, FaceSearchConfig(stack="s", legal_ok="2026-10-29"),
                                 ack) == []


def test_enable_refuses_before_touching_aws(monkeypatch, tmp_path):
    (tmp_path / "events" / "e").mkdir(parents=True)
    (tmp_path / "events" / "e" / "event.json").write_text(json.dumps(
        {"name": "E", "date": "2026-10-31", "face_search": {"stack": "s"}}))
    monkeypatch.setattr(cli, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(cli, "EVENTS_OUT", tmp_path / "out")
    monkeypatch.setattr(cli.FaceStack, "load", classmethod(lambda *a: pytest.fail("AWS touched")))
    with pytest.raises(SystemExit, match="parecer jurídico"):
        cli.face_search_cmd(argparse.Namespace(slug="e", action="enable", confirm_ai_opt_out=False))


def test_enable_turns_it_on_when_preconditions_hold(monkeypatch, tmp_path):
    (tmp_path / "events" / "e").mkdir(parents=True)
    path = tmp_path / "events" / "e" / "event.json"
    path.write_text(json.dumps({"name": "E", "date": "2026-10-31", "removal_contact": "a@b.c",
                                "face_search": {"stack": "s", "legal_ok": "2026-10-29"}}))
    monkeypatch.setattr(cli, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(cli, "EVENTS_OUT", tmp_path / "out")
    fake = stack(rek_exists=False)
    monkeypatch.setattr(cli.FaceStack, "load", classmethod(lambda *a: fake))
    cli.face_search_cmd(argparse.Namespace(slug="e", action="enable", confirm_ai_opt_out=True))
    assert json.loads(path.with_name("event.local.json").read_text()) == {"face_search": {"enabled": True}}
    assert "enabled" not in json.loads(path.read_text())["face_search"]  # the versioned file is left alone
    assert fake.clients["rekognition"].exists and fake.scheduled_for() == "at(2026-11-30T03:00:00)"
