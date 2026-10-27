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
