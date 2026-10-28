"""The event's look for the web pages: AWS Community Day Brasil — Edição Norte's official artwork.

Everything is inlined as data URIs: the gallery stays one HTML file, and the upload page ships to Lambda as a
single index.py. Sources and provenance are in assets/web/README.md.
"""
from __future__ import annotations

import base64
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "assets"
LOGO_ALT = "AWS Community Day Brasil — Edição Norte · Belém/PA"

# Sampled from the official agenda slide (assets/frames/aws-community-day-belem/source-agenda.jpg).
NAVY = "#091b33"
TOKENS = (":root{--navy:#091b33;--deep:#06111f;--raised:#11274a;--rule:#313453;--ink:#ffffff;--muted:#c4d0e6;"
          "--orange:#fb8617;--violet:#5446e1;--lavender:#8365c7;--good:#4cc38a;--bad:#ff6b6b;"
          "color-scheme:dark;accent-color:var(--orange);scrollbar-color:var(--rule) var(--navy)}")
FONT_STACK = 'Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'
# Pointy-top hexagon, as on the agenda's timeline.
HEX_PATH = "M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5z"


# The site icon: one cube of the masthead's artwork (assets/web/hex-right.webp) in its orange hexagon.
ICON_ORANGE, ICON_TOP, ICON_RIGHT, ICON_LEFT = "#fb8617", "#43395e", "#373153", "#122038"


def icon(size: int, rounded: bool):
    """The icon as a PIL image. Rounded corners for the browser tab; square and opaque for the phone's home screen,
    which rounds it itself and would turn transparent corners black."""
    import math

    from PIL import Image, ImageDraw

    big = 1024  # drawn large, then scaled down, for clean edges at 16 px

    def hexagon(r: float) -> list[tuple[float, float]]:  # pointy-top, from the top clockwise
        return [(big / 2 + r * math.cos(math.radians(a)), big / 2 + r * math.sin(math.radians(a)))
                for a in (-90, -30, 30, 90, 150, 210)]

    im = Image.new("RGBA" if rounded else "RGB", (big, big), (0, 0, 0, 0) if rounded else NAVY)
    d = ImageDraw.Draw(im)
    if rounded:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.22, fill=NAVY)
    outer, ring = big * 0.40, big * 0.098
    d.polygon(hexagon(outer), fill=ICON_ORANGE)
    d.polygon(hexagon(outer - ring), fill=NAVY)
    top, upper_right, lower_right, bottom, lower_left, upper_left = hexagon((outer - ring) * 0.80)
    center = (big / 2, big / 2)
    d.polygon([center, upper_left, top, upper_right], fill=ICON_TOP)
    d.polygon([center, upper_right, lower_right, bottom], fill=ICON_RIGHT)
    d.polygon([center, bottom, lower_left, upper_left], fill=ICON_LEFT)
    return im.resize((size, size), Image.LANCZOS)


def _data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


@cache
def assets() -> dict[str, str]:
    """{"font", "logo", "hex_left", "hex_right", "skyline"} as data URIs."""
    web = ROOT / "web"
    return {
        "font": _data_uri(web / "fonts" / "inter-latin.woff2", "font/woff2"),
        "logo": _data_uri(ROOT / "brand" / "cd-norte" / "logo.svg", "image/svg+xml"),
        "hex_left": _data_uri(web / "hex-left.webp", "image/webp"),
        "hex_right": _data_uri(web / "hex-right.webp", "image/webp"),
        "skyline": _data_uri(web / "skyline.webp", "image/webp"),
    }


def font_face(font_uri: str) -> str:
    return (f'@font-face{{font-family:Inter;font-style:normal;font-weight:400 800;font-display:swap;'
            f'src:url({font_uri}) format("woff2")}}')


def hex_svg(cls: str = "", size: int = 24) -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">'
            f'<path d="{HEX_PATH}"/></svg>')
