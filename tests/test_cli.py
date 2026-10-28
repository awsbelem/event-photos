import datetime as dt
import json
import os
import sys

import pytest

from event_photos import cli


def test_the_aws_cli_never_waits_on_a_pager(monkeypatch):
    # AWS CLI v2 pipes output to `less` when stdout is a terminal (ssh -t); the image has no less, so
    # the CloudFront invalidation failed after a whole publish.
    monkeypatch.setenv("AWS_PAGER", "less")
    monkeypatch.setattr(sys, "argv", ["event-photos", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    assert os.environ["AWS_PAGER"] == ""


def test_each_publish_adds_a_round_with_only_its_new_photos(tmp_path):
    site, log = tmp_path / "site", tmp_path / cli.ROUNDS
    site.mkdir()

    def publish(ids, uploads, hour):
        (site / "photos.json").write_text(json.dumps({"photos": [{"id": i} for i in ids]}))
        return cli.record_round(log, site, uploads, "America/Belem", dt.datetime(2026, 10, 31, hour, tzinfo=dt.timezone.utc))

    publish(["a", "b"], 3, 13)
    publish(["a", "b", "c", "d"], 7, 16)
    rounds = [json.loads(line) for line in log.read_text().splitlines()]
    assert rounds == [{"published": "2026-10-31T10:00:00-03:00", "uploads": 3, "new": ["a", "b"], "total": 2},
                      {"published": "2026-10-31T13:00:00-03:00", "uploads": 7, "new": ["c", "d"], "total": 4}]
