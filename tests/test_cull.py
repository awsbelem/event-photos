import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import imagehash
import numpy as np

from event_photos.cull import group_bursts

T0 = dt.datetime(2026, 10, 23, 23, 6, 0)


def _hash_with_bits_flipped(n: int) -> str:
    bits = np.zeros((8, 8), dtype=bool)
    bits.flat[:n] = True
    return str(imagehash.ImageHash(bits))


def _group(shots):
    """shots: (seconds after T0, bits different from the base hash)."""
    paths = [Path(f"IMG_{i}.jpg") for i in range(len(shots))]
    analyses = {p: SimpleNamespace(phash=_hash_with_bits_flipped(bits)) for p, (_, bits) in zip(paths, shots)}
    times = {p: T0 + dt.timedelta(seconds=s) for p, (s, _) in zip(paths, shots)}
    return [[p.name for p in g] for g in group_bursts(paths, analyses, times)]


def test_burst_tolerates_more_difference():
    assert _group([(0, 0), (2, 11)]) == [["IMG_0.jpg", "IMG_1.jpg"]]


def test_retake_of_the_same_pose_joins_the_group():
    assert _group([(0, 0), (14, 8), (20, 14)]) == [["IMG_0.jpg", "IMG_1.jpg", "IMG_2.jpg"]]


def test_retake_that_looks_different_stays_apart():
    assert _group([(0, 0), (14, 11)]) == [["IMG_0.jpg"], ["IMG_1.jpg"]]


def test_beyond_retake_gap_stays_apart():
    assert _group([(0, 0), (25, 0)]) == [["IMG_0.jpg"], ["IMG_1.jpg"]]
