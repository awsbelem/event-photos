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
