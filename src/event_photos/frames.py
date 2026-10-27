"""Branded frames for social sharing (feed 4:5 and story 9:16).

A frame template is a folder in one of two shapes:
- strips: the event artwork cut into header.png and footer.png (see
  scripts/make_frame_assets.py), plus an optional frame.json with `background`
  and `accent`; the photo sits between the strips.
- layered: frame.json lists, per format, the photo `box`, its corner `radius` and
  `border`; <format>-bg.png is drawn under the photo and the optional
  <format>-fg.png (with transparency) over it. See scripts/make_frames_cd_norte.py.
Either way the photo is cropped around the people in it. `label` in frame.json
names the frame for attendees choosing between several.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

FRAMES_DIR = Path(__file__).resolve().parents[2] / "assets" / "frames"
DEFAULT_TEMPLATE = FRAMES_DIR / "aws-community-day-belem"
DEFAULT_ACCENT = "#f28528"


@dataclass(frozen=True)
class FrameFormat:
    name: str
    width: int
    height: int
    top: int  # header offset; stories keep clear of the app's top bar
    margin: int


FORMATS = (
    FrameFormat("feed", 1080, 1350, top=0, margin=44),
    FrameFormat("story", 1080, 1920, top=90, margin=44),
)


@dataclass(frozen=True)
class Layer:
    background: Image.Image
    foreground: Image.Image | None
    box: tuple[int, int, int, int]
    radius: int
    border: int
    border_color: tuple[int, int, int]


@dataclass(frozen=True)
class FrameTemplate:
    key: str
    label: str
    header: Image.Image | None = None
    footer: Image.Image | None = None
    background: tuple[int, int, int] = (0, 0, 0)
    accent: tuple[int, int, int] = (0, 0, 0)
    layers: dict[str, Layer] | None = None  # by format name, for layered templates

    @classmethod
    def load(cls, folder: Path) -> FrameTemplate:
        config = json.loads((folder / "frame.json").read_text()) if (folder / "frame.json").exists() else {}
        label = config.get("label", folder.name)
        if "formats" in config:
            layers = {}
            for name, f in config["formats"].items():
                fg = folder / f"{name}-fg.png"
                layers[name] = Layer(Image.open(folder / f"{name}-bg.png").convert("RGB"),
                                     Image.open(fg).convert("RGBA") if fg.exists() else None,
                                     tuple(f["box"]), f.get("radius", 0), f.get("border", {}).get("width", 0),
                                     _rgb(f.get("border", {}).get("color", DEFAULT_ACCENT)))
            return cls(folder.name, label, layers=layers)
        header = Image.open(folder / "header.png").convert("RGB")
        background = (_rgb(config["background"]) if "background" in config
                      else header.getpixel((header.width // 2, header.height - 2)))
        return cls(folder.name, label, header=header, footer=Image.open(folder / "footer.png").convert("RGB"),
                   background=background, accent=_rgb(config.get("accent", DEFAULT_ACCENT)))


# Bump when the way a photo sits in its frame changes: it is part of the develop cache key, so every photo is
# framed again on the next run. 2: wide groups fitted whole fill the leftover with their own blur.
FRAMING = 2


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def face_crop_box(size: tuple[int, int], aspect: float,
                  faces: list[tuple[float, float, float, float]]) -> tuple[int, int, int, int]:
    """Largest crop of the given aspect (w/h), centered on the people.

    Faces are normalized (x0, y0, x1, y1). Heads sit in the upper part of a
    body, so the center is pushed down a little to keep torsos in. Without
    faces the crop is centered, slightly above the middle.
    """
    w, h = size
    cw, ch = (w, round(w / aspect)) if w / h < aspect else (round(h * aspect), h)
    if faces:
        x0 = min(f[0] for f in faces) * w
        x1 = max(f[2] for f in faces) * w
        y0 = min(f[1] for f in faces) * h
        y1 = max(f[3] for f in faces) * h
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + 0.15 * ch
        cy = min(cy, y0 + ch * 0.4)  # never push the top head out of frame
    else:
        cx, cy = w / 2, h * 0.45
    left = int(min(max(cx - cw / 2, 0), w - cw))
    top = int(min(max(cy - ch / 2, 0), h - ch))
    return left, top, left + cw, top + ch


def _blurred_backdrop(canvas: Image.Image, photo: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    """The photo itself, enlarged to cover the box, blurred and darkened: what shows around a photo fitted whole,
    instead of the frame's blank."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    small = photo.crop(face_crop_box(photo.size, bw / bh, [])).resize((max(1, bw // 8), max(1, bh // 8)))
    back = small.filter(ImageFilter.GaussianBlur(6)).resize((bw, bh), Image.LANCZOS)
    back = ImageEnhance.Brightness(back).enhance(0.6)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius, fill=255)
    canvas.paste(back, box[:2], mask)


def _cuts_faces(crop: tuple[int, int, int, int], size: tuple[int, int],
                faces: list[tuple[float, float, float, float]]) -> bool:
    w, h = size
    return any(f[0] * w < crop[0] - 2 or f[2] * w > crop[2] + 2 or f[1] * h < crop[1] - 2 or f[3] * h > crop[3] + 2
               for f in faces)


def frame_photo(src: Path, dst: Path, fmt: FrameFormat, template: FrameTemplate,
                faces: list[tuple[float, float, float, float]]) -> None:
    if template.layers:
        layer = template.layers[fmt.name]
        canvas = layer.background.copy()
        _place_photo(canvas, src, layer.box, faces, layer.radius, layer.border, layer.border_color)
        if layer.foreground:
            canvas.paste(layer.foreground, (0, 0), layer.foreground)
    else:
        canvas = Image.new("RGB", (fmt.width, fmt.height), template.background)
        canvas.paste(template.header, ((fmt.width - template.header.width) // 2, fmt.top))
        footer_top = fmt.height - template.footer.height
        canvas.paste(template.footer, ((fmt.width - template.footer.width) // 2, footer_top))
        box = (fmt.margin, fmt.top + template.header.height + 8, fmt.width - fmt.margin, footer_top - 10)
        _place_photo(canvas, src, box, faces, 26, 5, template.accent)
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "JPEG", quality=92)


def _place_photo(canvas: Image.Image, src: Path, box: tuple[int, int, int, int],
                 faces: list[tuple[float, float, float, float]], radius: int, border: int,
                 border_color: tuple[int, int, int]) -> None:
    window = box  # the frame's opening: its border goes around this, even when the photo inside is smaller
    bw, bh = box[2] - box[0], box[3] - box[1]
    with Image.open(src) as im:
        photo = im.convert("RGB")
    crop = face_crop_box(photo.size, bw / bh, faces)
    if _cuts_faces(crop, photo.size, faces):
        _blurred_backdrop(canvas, photo, box, radius)
        # Wide group in a tall frame: keep everyone, trimming only the sides
        # beyond the outermost faces, and fit the result instead of cutting people.
        pad = 0.06 * photo.width
        left = max(0, int(min(f[0] for f in faces) * photo.width - pad))
        right = min(photo.width, int(max(f[2] for f in faces) * photo.width + pad))
        photo = photo.crop((left, 0, right, photo.height))
        scale = min(bw / photo.width, bh / photo.height)
        fw, fh = round(photo.width * scale), round(photo.height * scale)
        box = (box[0] + (bw - fw) // 2, box[1] + (bh - fh) // 2, box[0] + (bw - fw) // 2 + fw, box[1] + (bh - fh) // 2 + fh)
        bw, bh = fw, fh
        photo = photo.resize((bw, bh), Image.LANCZOS)
    else:
        photo = photo.crop(crop).resize((bw, bh), Image.LANCZOS)

    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius, fill=255)
    canvas.paste(photo, box[:2], mask)
    if border:
        ImageDraw.Draw(canvas).rounded_rectangle(
            (window[0] - border, window[1] - border, window[2] + border - 1, window[3] + border - 1),
            radius + border if radius else 0, outline=border_color, width=border)
