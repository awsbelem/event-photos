"""Learned auto-enhancement and color looks, both as 3D LUTs.

Auto-enhancement uses Image-Adaptive 3D LUTs (Zeng et al., TPAMI 2020,
Apache-2.0), trained on MIT-Adobe FiveK retouches by expert C: a tiny CNN looks
at a 256x256 thumbnail and blends three basis LUTs into one tailored to the
photo. It only remaps tone and color, never invents detail, so faces stay intact.
The weights are converted once by scripts/export_fivek_lut.py.

Looks are 33^3 LUTs too, readable/writable as .cube so the same look can be
used in Lightroom, darktable or a phone editor.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

LUT_DIM = 33


def apply_lut(rgb: np.ndarray, lut: np.ndarray, rows_per_chunk: int = 256) -> np.ndarray:
    """Trilinear lookup. rgb: HxWx3 float in [0,1]; lut: (3, B, G, R) like the FiveK kernels.

    Works in row strips: the interpolation needs ~15 full-size temporaries,
    over 2 GB for a 12 MP photo if done in one go.
    """
    table = np.ascontiguousarray(np.moveaxis(lut, 0, -1))  # (B, G, R, 3)
    out = np.empty(rgb.shape, dtype=np.float32)
    for y in range(0, rgb.shape[0], rows_per_chunk):
        out[y:y + rows_per_chunk] = _apply_table(rgb[y:y + rows_per_chunk], table)
    return out


def _apply_table(rgb: np.ndarray, table: np.ndarray) -> np.ndarray:
    dim = table.shape[0]
    x = np.clip(rgb, 0.0, 1.0) * (dim - 1)
    i0 = np.minimum(x.astype(np.int32), dim - 2)
    f = (x - i0).astype(np.float32)
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]

    def at(db: int, dg: int, dr: int) -> np.ndarray:
        return table[b0 + db, g0 + dg, r0 + dr]

    c00 = at(0, 0, 0) * (1 - fr) + at(0, 0, 1) * fr
    c01 = at(0, 1, 0) * (1 - fr) + at(0, 1, 1) * fr
    c10 = at(1, 0, 0) * (1 - fr) + at(1, 0, 1) * fr
    c11 = at(1, 1, 0) * (1 - fr) + at(1, 1, 1) * fr
    c0 = c00 * (1 - fg) + c01 * fg
    c1 = c10 * (1 - fg) + c11 * fg
    return np.clip(c0 * (1 - fb) + c1 * fb, 0.0, 1.0).astype(np.float32)


def identity_lut(dim: int = LUT_DIM) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, dim, dtype=np.float32)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([r, g, b])


class FiveKEnhancer:
    def __init__(self, models_dir: Path):
        self._net = cv2.dnn.readNetFromONNX(str(models_dir / "fivek_lut_classifier.onnx"))
        self._basis = np.load(models_dir / "fivek_lut_basis.npy")  # (3 LUTs, 3, B, G, R)

    def lut_for(self, rgb: np.ndarray) -> np.ndarray:
        thumb = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA)
        self._net.setInput(np.ascontiguousarray(thumb.transpose(2, 0, 1)[None], dtype=np.float32))
        weights = self._net.forward().reshape(-1)
        return np.tensordot(weights, self._basis, axes=1).astype(np.float32)

    def enhance(self, rgb: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """rgb: HxWx3 float sRGB in [0,1]. strength blends toward the original."""
        lut = self.lut_for(rgb)
        if strength != 1.0:
            lut = identity_lut(lut.shape[-1]) + strength * (lut - identity_lut(lut.shape[-1]))
        return apply_lut(rgb, lut)


def _warm_clean(rgb: np.ndarray) -> np.ndarray:
    """Event look: slightly warm, soft contrast, gentle saturation, lifted blacks."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    out = np.stack([r * 1.03 + 0.008, g * 1.005, b * 0.95], axis=-1)
    s = np.clip(out, 0, 1)
    out = s + 0.35 * (s * s * (3 - 2 * s) - s)  # soft S-curve
    luma = out @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    out = luma[..., None] + 1.06 * (out - luma[..., None])
    return np.clip(0.025 + out * 0.975, 0, 1)


LOOKS = {"warm-clean": _warm_clean}


def bake_look(name: str, dim: int = LUT_DIM) -> np.ndarray:
    ident = identity_lut(dim)
    return np.moveaxis(LOOKS[name](np.moveaxis(ident, 0, -1)), -1, 0).astype(np.float32)


def write_cube(lut: np.ndarray, path: Path, title: str) -> None:
    """Adobe .cube: red varies fastest, then green, then blue — same as (3, B, G, R)."""
    dim = lut.shape[-1]
    rows = np.moveaxis(lut, 0, -1).reshape(-1, 3)
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {dim}", *(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in rows)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def read_cube(path: Path) -> np.ndarray:
    dim, rows = None, []
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "LUT_3D_SIZE":
            dim = int(parts[1])
        elif len(parts) == 3 and parts[0][0] in "0123456789.-":
            rows.append([float(v) for v in parts])
    if dim is None or len(rows) != dim ** 3:
        raise ValueError(f"not a 3D .cube LUT: {path}")
    return np.moveaxis(np.asarray(rows, dtype=np.float32).reshape(dim, dim, dim, 3), -1, 0)
