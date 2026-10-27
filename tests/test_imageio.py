import numpy as np
from PIL import Image

from event_photos import imageio
from event_photos.imageio import load_camera_rendering, load_linear


def photo(path, size, orientation=None):
    im = Image.fromarray(np.full((size[1], size[0], 3), 128, np.uint8))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    im.save(path, exif=exif)
    return path


def test_large_photos_are_decoded_at_most_at_the_cap(tmp_path, monkeypatch):
    # A 48 MP iPhone photo took 3.2 GB to process: more than the server's container allows.
    monkeypatch.setattr(imageio, "MAX_LONG_SIDE", 100)
    path = photo(tmp_path / "big.jpg", (300, 200))
    assert load_camera_rendering(path).shape == (67, 100, 3)
    assert load_linear(path).shape == (67, 100, 3)


def test_the_cap_applies_after_the_photo_is_turned_upright(tmp_path, monkeypatch):
    monkeypatch.setattr(imageio, "MAX_LONG_SIDE", 100)
    path = photo(tmp_path / "portrait.jpg", (300, 200), orientation=6)  # stored sideways
    assert load_camera_rendering(path).shape == (100, 67, 3)


def test_photos_within_the_cap_keep_their_size(tmp_path):
    path = photo(tmp_path / "small.jpg", (300, 200))
    assert load_camera_rendering(path).shape == (200, 300, 3)


def test_a_cap_of_zero_keeps_the_original_size(tmp_path, monkeypatch):
    monkeypatch.setattr(imageio, "MAX_LONG_SIDE", 0)
    path = photo(tmp_path / "big.jpg", (300, 200))
    assert load_camera_rendering(path).shape == (200, 300, 3) and load_linear(path).shape == (200, 300, 3)
