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
