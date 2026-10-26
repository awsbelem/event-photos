"""Cut the header and skyline out of the AWS Community Day Belém agenda post.

  uv run python scripts/make_frame_assets.py <agenda post 1080x1350> assets/frames/aws-community-day-belem

The source art is a carousel slide: the "2/8" page badge over the skyline is
painted out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HEADER = (0, 0, 1080, 180)
FOOTER = (0, 1100, 1080, 1350)
PAGE_BADGE = (948, 1282, 1026, 1333)  # in source coordinates


def main(src: Path, out: Path) -> None:
    art = np.asarray(Image.open(src).convert("RGB")).copy()
    if art.shape[:2] != (1350, 1080):
        raise SystemExit(f"expected the 1080x1350 agenda post, got {art.shape[1]}x{art.shape[0]}")
    mask = np.zeros(art.shape[:2], np.uint8)
    x0, y0, x1, y1 = PAGE_BADGE
    mask[y0:y1, x0:x1] = 255
    art = cv2.inpaint(art, mask, 9, cv2.INPAINT_TELEA)
    out.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(art)
    image.crop(HEADER).save(out / "header.png")
    image.crop(FOOTER).save(out / "footer.png")
    print(f"wrote {out}/header.png, footer.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
