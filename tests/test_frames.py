from pathlib import Path

from PIL import Image

from event_photos.frames import FORMATS, FRAMES_DIR, FrameTemplate, frame_photo


def test_layered_frames_render_at_instagram_sizes(tmp_path):
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (4000, 3000), (200, 120, 60)).save(src)
    for key in ("cd-norte-classica", "cd-norte-hexagonos", "cd-norte-cartao"):
        template = FrameTemplate.load(FRAMES_DIR / key)
        assert template.layers and template.label
        for fmt in FORMATS:
            out = tmp_path / key / f"{fmt.name}.jpg"
            frame_photo(src, out, fmt, template, [])
            assert Image.open(out).size == (fmt.width, fmt.height)
            x0, y0, x1, y1 = template.layers[fmt.name].box
            assert Image.open(out).getpixel(((x0 + x1) // 2, (y0 + y1) // 2))[0] > 150  # the photo shows in the box


def test_a_wide_group_fills_the_box_with_its_own_blur_instead_of_blank(tmp_path):
    # People at both edges cannot be cropped to a tall box: the photo is fitted whole, and the bands it leaves
    # showed the card's blank white.
    src = tmp_path / "group.jpg"
    Image.new("RGB", (4000, 2000), (60, 120, 200)).save(src)
    faces = [(0.02, 0.4, 0.12, 0.6), (0.88, 0.4, 0.98, 0.6)]
    template = FrameTemplate.load(FRAMES_DIR / "cd-norte-cartao")
    feed = next(f for f in FORMATS if f.name == "feed")
    out = tmp_path / "framed.jpg"
    frame_photo(src, out, feed, template, faces)
    x0, y0, x1, y1 = template.layers["feed"].box
    band = Image.open(out).getpixel(((x0 + x1) // 2, y0 + 12))
    center = Image.open(out).getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
    assert band[2] > band[0] + 30 and sum(band) < 3 * 200  # the photo's own color, darker; not the white card
    assert abs(center[2] - 200) < 12 and abs(center[0] - 60) < 12  # the photo itself, untouched


def test_changing_how_photos_are_fitted_reframes_cached_photos():
    from event_photos.frames import FRAMING
    from event_photos.pipeline import Settings
    assert Settings().develop_key()["framing"] == FRAMING


def test_the_frame_border_goes_around_the_whole_window_not_the_fitted_photo(tmp_path):
    src = tmp_path / "group.jpg"
    Image.new("RGB", (4000, 2000), (60, 120, 200)).save(src)
    template = FrameTemplate.load(FRAMES_DIR / "cd-norte-classica")  # orange border, 6 px
    feed = next(f for f in FORMATS if f.name == "feed")
    out = tmp_path / "framed.jpg"
    frame_photo(src, out, feed, template, [(0.02, 0.4, 0.12, 0.6), (0.88, 0.4, 0.98, 0.6)])
    x0, y0, x1, y1 = template.layers["feed"].box
    r, g, b = Image.open(out).getpixel((x0 - 3, y0 + 60))  # beside the blurred band, above the photo
    assert r > 200 and 120 < g < 190 and b < 80  # #FF9900
