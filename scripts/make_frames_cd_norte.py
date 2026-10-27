"""Draw the three AWS Community Day Norte frames attendees choose from, from the brand kit.

    uv run python scripts/make_frames_cd_norte.py

Writes assets/frames/cd-norte-{classica,hexagonos,cartao}/ as layered templates (see frames.py).
Kit rules followed: logo first, centered on top with breathing room; hexagons only in opposite
corners; orange to call attention, white to read; one gradient per art; the map never behind photos.
Stories keep text out of the top ~200 px and bottom ~220 px, where Instagram draws its own controls.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "assets" / "brand" / "cd-norte"
OUT = ROOT / "assets" / "frames"
KIT = json.loads((BRAND / "brand.json").read_text())

AMEIXA = (0x42, 0x31, 0x4B)
LARANJA = (0xFF, 0x99, 0x00)
EU_FUI = {"feed": 88, "story": 94}  # px of the card's "Eu fui!"
CUIA = {"feed": 260, "story": 310}  # px width of the cuia de tacacá on the card's corner
BRANCO = (255, 255, 255)
LILAS = (0xA6, 0xA6, 0xE6)
SUNSET = ((0xFF, 0x43, 0x53), (0xFF, 0xD2, 0x9A))
HANDLE, PLACE = KIT["handle"], KIT["place_date"]
SIZES = {"feed": (1080, 1350), "story": (1080, 1920)}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BRAND / "fonts" / f"{name}.ttf"), size)


def asset(name: str, width: int) -> Image.Image:
    im = Image.open(BRAND / name).convert("RGBA")
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


def text_width(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, tracking: int = 0) -> int:
    return round(draw.textlength(text, font=f)) + tracking * (len(text) - 1)


def draw_text(img: Image.Image, xy: tuple[int, int], text: str, f: ImageFont.FreeTypeFont, fill,
              tracking: int = 0, anchor: str = "la") -> None:
    """Text with letter spacing; anchor 'ma' centers on x."""
    draw = ImageDraw.Draw(img)
    x, y = xy
    if anchor == "ma":
        x -= text_width(draw, text, f, tracking) // 2
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += round(draw.textlength(ch, font=f)) + tracking


def gradient_text(img: Image.Image, center_x: int, y: int, text: str, f: ImageFont.FreeTypeFont) -> None:
    """The art's one gradient: sunset, left to right."""
    probe = ImageDraw.Draw(img)
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=f)
    w, h = x1 - x0 + 8, y1 - y0 + 8
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((4 - x0, 4 - y0), text, font=f, fill=255)
    ramp = Image.new("RGB", (w, h))
    (a, b), px = SUNSET, ramp.load()
    for i in range(w):
        t = i / max(w - 1, 1)
        c = tuple(round(a[k] + (b[k] - a[k]) * t) for k in range(3))
        for j in range(h):
            px[i, j] = c
    img.paste(ramp, (center_x - w // 2, y), mask)


def logo(img: Image.Image, width: int, top: int) -> int:
    mark = asset("logo.png", width)
    img.paste(mark, ((img.width - width) // 2, top), mark)
    return top + mark.height


def footer_lines(img: Image.Image, y: int, place: bool = True) -> None:
    draw_text(img, (img.width // 2, y), HANDLE, font("IBMPlexSans-Bold", 34), LARANJA, 1, "ma")
    if place:
        draw_text(img, (img.width // 2, y + 50), PLACE, font("IBMPlexSans-Regular", 26), LILAS, 1, "ma")


def market(img: Image.Image, width: int) -> None:
    """Mercado de São Brás in white line art, standing on the bottom edge at the right."""
    art = asset("belem.png", width)
    img.paste(art, (img.width - art.width - 24, img.height - art.height), art)


def classica(fmt: str) -> tuple[Image.Image, Image.Image | None, dict]:
    """Logo on top, photo with an orange outline, the handle and Mercado de São Brás below."""
    w, h = SIZES[fmt]
    bg = Image.new("RGB", (w, h), AMEIXA)
    story = fmt == "story"
    bottom = logo(bg, 500 if story else 460, 200 if story else 48)
    foot = h - (340 if story else 170)
    box = [64, bottom + (48 if story else 32), w - 64, foot - 24]
    market(bg, 340 if story else 260)
    footer_lines(bg, foot + (60 if story else 24))
    return bg, None, {"box": box, "radius": 28, "border": {"width": 6, "color": "#FF9900"}}


def flush_corner(img: Image.Image, cluster: Image.Image) -> None:
    """Pastes a hexagon cluster into the corner its artwork is cut for: the edges where the drawing
    is sliced off sit exactly on the frame's edges, so the cut reads as running off the page."""
    x0, y0, x1, y1 = cluster.getbbox()
    x = 0 if x0 == 0 else img.width - cluster.width if x1 == cluster.width else 0
    y = 0 if y0 == 0 else img.height - cluster.height if y1 == cluster.height else 0
    img.paste(cluster, (x, y), cluster)


def hexagonos(fmt: str) -> tuple[Image.Image, Image.Image | None, dict]:
    """Hexagons in opposite corners, each flush with the edges it is cut on (A: top and right,
    B: bottom and left); photo in a white mount like the speaker cards."""
    w, h = SIZES[fmt]
    bg = Image.new("RGB", (w, h), AMEIXA)
    story = fmt == "story"
    size = 330 if story else 230
    flush_corner(bg, asset("hexA.png", size))
    flush_corner(bg, asset("hexB.png", size))
    bottom = logo(bg, 420 if story else 400, 200 if story else 48)
    foot = h - (340 if story else 150)
    box = [96, bottom + (60 if story else 40), w - 96, foot - 40]
    market(bg, 380 if story else 260)
    draw_text(bg, (w // 2, foot + (70 if story else 30)), HANDLE, font("IBMPlexSans-Bold", 34), LARANJA, 1, "ma")
    return bg, None, {"box": box, "radius": 0, "border": {"width": 16, "color": "#FFFFFF"}}


def cartao(fmt: str) -> tuple[Image.Image, Image.Image, dict]:
    """A white instant-photo card with a sunset 'Eu fui!' and a cuia de tacacá on its corner."""
    w, h = SIZES[fmt]
    bg = Image.new("RGB", (w, h), AMEIXA)
    story = fmt == "story"
    bottom = logo(bg, 460 if story else 400, 200 if story else 40)
    foot = h - (320 if story else 120)
    card = [70, bottom + (50 if story else 28), w - 70, foot - 30]
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle(card, 22, fill=BRANCO)
    caption_h = 150 if story else 128
    box = [card[0] + 30, card[1] + 30, card[2] - 30, card[3] - caption_h]
    date_x = card[2] - 40 - max(text_width(draw, "31.10.2026", font("IBMPlexSans-Bold", 30), 1),
                                text_width(draw, "Faci Wyden · Belém", font("IBMPlexSans-Regular", 24), 0))
    draw_text(bg, (card[2] - 40 - text_width(draw, "31.10.2026", font("IBMPlexSans-Bold", 30), 1),
                   card[3] - caption_h + 32), "31.10.2026", font("IBMPlexSans-Bold", 30), AMEIXA, 1)
    draw_text(bg, (card[2] - 40 - text_width(draw, "Faci Wyden · Belém", font("IBMPlexSans-Regular", 24), 0),
                   card[3] - caption_h + 74), "Faci Wyden · Belém", font("IBMPlexSans-Regular", 24), (0x69, 0x4D, 0x82))
    draw_text(bg, (w // 2, foot + (40 if story else 30)), HANDLE, font("IBMPlexSans-Bold", 34), LARANJA, 1, "ma")
    fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cuia = asset("tacaca.png", CUIA[fmt]).rotate(-8, expand=True, resample=Image.BICUBIC)
    cuia_x = card[0] - 40
    fg.paste(cuia, (cuia_x, card[3] - caption_h - cuia.height // 2 + 10), cuia)
    # "Eu fui!" sits in the middle of the room the cuia and the date leave, so neither crowds it as they grow.
    cuia_right = cuia_x + cuia.getbbox()[2]
    gradient_text(bg, (cuia_right + date_x) // 2, card[3] - caption_h + 14,
                  "Eu fui!", font("PermanentMarker-Regular", EU_FUI[fmt]))
    return bg, fg, {"box": box, "radius": 6, "border": {"width": 0}}


DESIGNS = {"classica": ("Clássica", classica), "hexagonos": ("Hexágonos", hexagonos), "cartao": ("Cartão", cartao)}


def placeholder(size: tuple[int, int]) -> Image.Image:
    """Stand-in photo for the chooser swatch: a soft lavender ramp."""
    w, h = size
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        for x in range(w):
            px[x, y] = (round(0xB8 - 40 * t), round(0xA9 - 50 * t), round(0xD6 - 30 * t))
    return im


def main() -> None:
    for key, (label, draw) in DESIGNS.items():
        folder = OUT / f"cd-norte-{key}"
        folder.mkdir(parents=True, exist_ok=True)
        formats = {}
        for fmt in SIZES:
            bg, fg, spec = draw(fmt)
            bg.save(folder / f"{fmt}-bg.png", optimize=True)
            if fg:
                fg.save(folder / f"{fmt}-fg.png", optimize=True)
            elif (folder / f"{fmt}-fg.png").exists():
                (folder / f"{fmt}-fg.png").unlink()
            formats[fmt] = spec
            if fmt == "feed":  # chooser swatch: the feed frame around a placeholder photo
                x0, y0, x1, y1 = spec["box"]
                sample = bg.copy()
                sample.paste(placeholder((x1 - x0, y1 - y0)), (x0, y0))
                if spec.get("border", {}).get("width"):
                    bw = spec["border"]["width"]
                    ImageDraw.Draw(sample).rectangle((x0 - bw, y0 - bw, x1 + bw - 1, y1 + bw - 1),
                                                     outline=spec["border"]["color"], width=bw)
                if fg:
                    sample.paste(fg, (0, 0), fg)
                sample.thumbnail((192, 240), Image.LANCZOS)
                sample.save(folder / "swatch.png", optimize=True)
        (folder / "frame.json").write_text(json.dumps({"label": label, "formats": formats}, ensure_ascii=False,
                                                      indent=1) + "\n")
        print(f"{folder.relative_to(ROOT)}: {label}")


if __name__ == "__main__":
    main()
