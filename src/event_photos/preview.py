"""Link previews: what WhatsApp, LinkedIn and others show when the gallery's link, or one photo's, is pasted.

Crawlers read Open Graph tags and run no script, so each shared photo gets a tiny page of its own (p/<id>.html)
whose tags point at its card; a visitor landing there is sent on to the photo in the gallery. Cards are 1200×630,
the shape every one of those apps shows large without cropping.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFilter

from . import brand

HOME_CARD = "og.jpg"
CARD_DIR = "og"  # og/<id>.jpg
PAGE_DIR = "p"  # p/<id>.html
CARD = (1200, 630)
QUALITY = 80
_BRAND = brand.ROOT / "brand" / "cd-norte"


def photo_url(photo_id: str) -> str:
    """The page's address, relative to the gallery's root."""
    return f"{PAGE_DIR}/{quote(photo_id)}.html"


def _cover(im: Image.Image, size: tuple[int, int], focus: tuple[float, float] = (.5, .5)) -> Image.Image:
    """Fill `size` with `im`, cropping around `focus` (fractions of the photo) rather than its center."""
    w, h = size
    scale = max(w / im.width, h / im.height)
    sw, sh = round(im.width * scale), round(im.height * scale)
    left = min(max(round(focus[0] * sw - w / 2), 0), sw - w)
    top = min(max(round(focus[1] * sh - h / 2), 0), sh - h)
    return im.resize((sw, sh), Image.LANCZOS).crop((left, top, left + w, top + h))


def _rounded(im: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=radius, fill=255)
    out = Image.new("RGBA", im.size)
    out.paste(im, (0, 0), mask)
    return out


def faces_center(faces: list[dict]) -> tuple[float, float]:
    """Middle of the faces' boxes ([x0, y0, x1, y1] fractions), so a crop keeps the people; else the photo's center."""
    if not faces:
        return .5, .5
    x0, y0 = min(f["box"][0] for f in faces), min(f["box"][1] for f in faces)
    x1, y1 = max(f["box"][2] for f in faces), max(f["box"][3] for f in faces)
    return (x0 + x1) / 2, (y0 + y1) / 2


def photo_card(source: Path) -> Image.Image:
    """The whole photo over a blurred, navy-tinted copy of itself, as on the venue screen."""
    with Image.open(source) as im:
        im = im.convert("RGB")
        back = _cover(im.reduce(8) if min(im.size) > 800 else im, (CARD[0] // 4, CARD[1] // 4))
        back = back.filter(ImageFilter.GaussianBlur(6)).resize(CARD, Image.BILINEAR)
        card = Image.blend(back, Image.new("RGB", CARD, brand.NAVY), .6)
        im.thumbnail((CARD[0] - 80, CARD[1] - 48), Image.LANCZOS)
        card.paste(im, ((CARD[0] - im.width) // 2, (CARD[1] - im.height) // 2))
    return card


def home_card(photos: list[tuple[Path, tuple[float, float]]]) -> Image.Image:
    """The event's artwork and logo beside up to three photos of the day (one large, two below it)."""
    card = Image.new("RGB", CARD, brand.NAVY)
    m, gap = 24, 16
    hexes = Image.open(_BRAND / "hexB.png").convert("RGBA")  # the artwork's bottom-left corner piece
    hexes.thumbnail((300, 300), Image.LANCZOS)
    card.paste(hexes, (0, CARD[1] - hexes.height), hexes)
    logo = Image.open(_BRAND / "logo.png").convert("RGBA")
    logo.thumbnail((360, 360), Image.LANCZOS)
    left = 440 if photos else CARD[0]
    card.paste(logo, ((left - logo.width) // 2, 150), logo)
    if not photos:
        return card
    x, w, h = left, CARD[0] - left - m, CARD[1] - 2 * m
    slots = ([(x, m, w, h)] if len(photos) == 1 else
             [(x, m, w, round(h * .64)), (x, m + round(h * .64) + gap, w, h - round(h * .64) - gap)])
    if len(photos) > 2:
        top, bottom = slots
        half = (w - gap) // 2
        slots = [top, (x, bottom[1], half, bottom[3]), (x + half + gap, bottom[1], w - half - gap, bottom[3])]
    for (path, focus), (sx, sy, sw, sh) in zip(photos, slots):
        with Image.open(path) as im:
            tile = _rounded(_cover(im.convert("RGB"), (sw, sh), focus), 14)
        card.paste(tile, (sx, sy), tile)
    return card


def save(card: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    card.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True)


def tags(url: str, title: str, description: str, image: str, image_alt: str) -> str:
    """Open Graph and Twitter tags. `url` and `image` must be absolute: crawlers resolve nothing."""
    pairs = [("og:type", "website"), ("og:locale", "pt_BR"), ("og:title", title), ("og:description", description),
             ("og:url", url)]
    if image:
        pairs += [("og:image", image), ("og:image:width", str(CARD[0])), ("og:image:height", str(CARD[1])),
                  ("og:image:alt", image_alt)]
    meta = "".join(f'<meta property="{k}" content="{escape(v)}">' for k, v in pairs if v)
    if image:
        meta += '<meta name="twitter:card" content="summary_large_image">'
    return meta + (f'<meta name="description" content="{escape(description)}">' if description else "")


def photo_page(photo_id: str, title: str, description: str, alt: str, base_url: str) -> str:
    """p/<id>.html: the photo's preview for crawlers; people are sent straight on to it in the gallery."""
    target = f"../#foto={quote(photo_id)}"
    url = f"{base_url}/{photo_url(photo_id)}" if base_url else ""
    image = f"{base_url}/{CARD_DIR}/{quote(photo_id)}.jpg" if base_url else ""
    # A script, not <meta http-equiv="refresh">: some crawlers follow a refresh and would show the gallery's preview.
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="{brand.NAVY}">
<title>{escape(title)}</title>
{tags(url, title, description, image, alt)}
<script>location.replace({json.dumps(target)});</script>
</head><body style="background:{brand.NAVY};color:#fff;font:16px system-ui,sans-serif;padding:24px">
<p><a href="{escape(target)}" style="color:#fb8617">Ver a foto na galeria</a></p>
</body></html>
"""
