"""Photo discovery, capture-time metadata and decoding to linear sRGB."""
from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pillow_heif
import rawpy
from PIL import Image, ImageCms, ImageOps

pillow_heif.register_heif_opener()

RAW_EXTENSIONS = {".dng"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif", ".png"}


def list_photos(folder: Path) -> list[Path]:
    allowed = RAW_EXTENSIONS | IMAGE_EXTENSIONS
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in allowed)


def read_capture_times(paths: list[Path]) -> dict[Path, dt.datetime | None]:
    """Batch-read DateTimeOriginal (+ subseconds) with exiftool."""
    if not paths:
        return {}
    cmd = ["exiftool", "-json", "-q", "-DateTimeOriginal", "-SubSecTimeOriginal",
           "-d", "%Y-%m-%dT%H:%M:%S", *map(str, paths)]
    rows = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout or "[]")
    times: dict[Path, dt.datetime | None] = {p: None for p in paths}
    for row in rows:
        raw = row.get("DateTimeOriginal")
        if not isinstance(raw, str):
            continue
        try:
            when = dt.datetime.fromisoformat(raw)
        except ValueError:
            continue
        subsec = str(row.get("SubSecTimeOriginal", "") or "")
        if subsec.isdigit():
            when += dt.timedelta(seconds=float(f"0.{subsec}"))
        times[Path(row["SourceFile"])] = when
    return times


def read_image_sizes(paths: list[Path]) -> dict[Path, tuple[int, int] | None]:
    """Batch-read pixel size (width, height) with exiftool."""
    if not paths:
        return {}
    cmd = ["exiftool", "-json", "-q", "-n", "-ImageSize", *map(str, paths)]
    rows = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout or "[]")
    sizes: dict[Path, tuple[int, int] | None] = {p: None for p in paths}
    for row in rows:
        w, _, h = str(row.get("ImageSize", "")).replace("x", " ").partition(" ")
        if w.isdigit() and h.isdigit():
            sizes[Path(row["SourceFile"])] = (int(w), int(h))
    return sizes


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def _to_srgb_pil(im: Image.Image) -> Image.Image:
    """Convert embedded profiles (iPhone HEIC is Display P3) to sRGB."""
    icc = im.info.get("icc_profile")
    im = im.convert("RGB")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except ImageCms.PyCMSError:
            pass
    return im


def _baseline_exposure(path: Path) -> float:
    """DNG BaselineExposure in EV. Apple ProRAW stores ~+1..+3 EV here; LibRaw ignores it."""
    out = subprocess.run(["exiftool", "-q", "-n", "-s3", "-BaselineExposure", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def load_linear(path: Path) -> np.ndarray:
    """Decode any supported photo to a float32 HxWx3 array in linear sRGB."""
    if path.suffix.lower() in RAW_EXTENSIONS:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=16, no_auto_bright=True,
                                  gamma=(1, 1), output_color=rawpy.ColorSpace.sRGB)
        return rgb.astype(np.float32) / 65535.0 * np.float32(2.0 ** _baseline_exposure(path))
    with Image.open(path) as im:
        im = _to_srgb_pil(ImageOps.exif_transpose(im))
        return srgb_to_linear(np.asarray(im, dtype=np.float32) / 255.0)


_ORIENTATION_TRANSPOSE = {2: Image.FLIP_LEFT_RIGHT, 3: Image.ROTATE_180, 4: Image.FLIP_TOP_BOTTOM,
                          5: Image.TRANSPOSE, 6: Image.ROTATE_270, 7: Image.TRANSVERSE, 8: Image.ROTATE_90}


def load_camera_rendering(path: Path) -> np.ndarray:
    """The phone's own processed image as uint8 sRGB (Smart HDR, face-aware tone).

    For ProRAW that is the full-size JPEG preview embedded in the DNG, which
    carries no orientation of its own: the DNG's orientation is applied.
    """
    if path.suffix.lower() not in RAW_EXTENSIONS:
        with Image.open(path) as im:
            return np.asarray(_to_srgb_pil(ImageOps.exif_transpose(im)))
    data = subprocess.run(["exiftool", "-b", "-PreviewImage", str(path)], capture_output=True).stdout
    orientation = subprocess.run(["exiftool", "-q", "-n", "-s3", "-Orientation", str(path)],
                                 capture_output=True, text=True).stdout.strip()
    with Image.open(io.BytesIO(data)) as im:
        im = _to_srgb_pil(im)
    if orientation.isdigit() and int(orientation) in _ORIENTATION_TRANSPOSE:
        im = im.transpose(_ORIENTATION_TRANSPOSE[int(orientation)])
    return np.asarray(im)


def to_uint8_srgb(linear: np.ndarray) -> np.ndarray:
    return (linear_to_srgb(linear) * 255.0 + 0.5).astype(np.uint8)


def resize_long_side(rgb8: np.ndarray, long_side: int) -> np.ndarray:
    h, w = rgb8.shape[:2]
    scale = long_side / max(h, w)
    if scale >= 1:
        return rgb8
    im = Image.fromarray(rgb8).resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return np.asarray(im)


def save_jpeg(rgb8: np.ndarray, path: Path, quality: int = 92) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    srgb_icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(rgb8).save(path, "JPEG", quality=quality, icc_profile=srgb_icc, optimize=True)
