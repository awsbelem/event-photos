"""Create degraded copies of sample photos to exercise culling and correction.

Usage: uv run python -I scripts/make_synthetic.py samples/raw samples/test
"""
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for p in sorted(src.iterdir()):
    if p.suffix.lower() in {".jpg", ".jpeg", ".dng", ".heic"}:
        shutil.copy2(p, dst / p.name)

def load(name):
    return cv2.imread(str(src / name)).astype(np.float32) / 255

def save(img, name):
    cv2.imwrite(str(dst / name), (np.clip(img, 0, 1) * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])

lin = lambda x: x ** 2.2
gam = lambda x: np.clip(x, 0, 1) ** (1 / 2.2)

save(gam(lin(load("commons_00.jpg")) * 0.3), "synth_under_commons_00.jpg")       # -1.7 EV
save(gam(lin(load("commons_05.jpg")) * [0.75, 0.95, 1.25]), "synth_warm_commons_05.jpg")  # tungsten cast (BGR)
kernel = np.zeros((31, 31), np.float32); kernel[15, :] = 1 / 31
save(cv2.filter2D(load("commons_08.jpg"), -1, kernel), "synth_blur_commons_08.jpg")  # motion blur
img = load("commons_10.jpg"); h, w = img.shape[:2]
save(cv2.resize(img[10:h - 10, 14:w - 6], (w, h)), "synth_dup_commons_10.jpg")      # burst neighbour
print("ok", len(list(dst.iterdir())), "files")
