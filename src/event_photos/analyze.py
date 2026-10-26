"""Per-photo quality signals: sharpness, exposure, faces/blinks, perceptual hash.

Face handling is detection + landmarks only (no identity embeddings are computed
or stored), used to find closed eyes and to weight exposure toward people.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import imagehash
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image

ANALYSIS_LONG_SIDE = 1600
MIN_FACE_WIDTH = 0.03  # fraction of image width; smaller faces are ignored
BLINK_THRESHOLD = 0.5


@dataclass
class Face:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 normalized
    blink_left: float
    blink_right: float

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def eyes_closed(self) -> bool:
        return min(self.blink_left, self.blink_right) > BLINK_THRESHOLD


@dataclass
class Analysis:
    sharpness: float
    median_luma: float
    clipped_highlights: float
    crushed_shadows: float
    phash: str
    faces: list[Face] = field(default_factory=list)

    @property
    def main_face(self) -> Face | None:
        return max(self.faces, key=lambda f: f.width, default=None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["faces"] = [asdict(f) | {"eyes_closed": f.eyes_closed} for f in self.faces]
        return d


class Analyzer:
    """YuNet finds faces (handles small faces in group shots); MediaPipe then
    reads blink blendshapes on each face crop. MediaPipe's own detector is
    short-range and misses most faces in group photos.
    """

    def __init__(self, models_dir: Path):
        self._detector = cv2.FaceDetectorYN.create(
            str(models_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.6, 0.3, 5000)
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(models_dir / "face_landmarker.task")),
            num_faces=1,
            output_face_blendshapes=True,
            min_face_detection_confidence=0.3,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def close(self) -> None:
        self._landmarker.close()

    def analyze(self, rgb8: np.ndarray) -> Analysis:
        gray = cv2.cvtColor(rgb8, cv2.COLOR_RGB2GRAY)
        faces = self._faces(rgb8)
        luma = gray.astype(np.float32) / 255.0
        return Analysis(
            sharpness=_sharpness(gray, faces),
            median_luma=float(np.median(luma)),
            clipped_highlights=float((rgb8.min(axis=2) >= 250).mean()),
            crushed_shadows=float((rgb8.max(axis=2) <= 5).mean()),
            phash=str(imagehash.phash(Image.fromarray(rgb8))),
            faces=faces,
        )

    def _faces(self, rgb8: np.ndarray) -> list[Face]:
        h, w = rgb8.shape[:2]
        self._detector.setInputSize((w, h))
        _, detections = self._detector.detect(np.ascontiguousarray(rgb8[:, :, ::-1]))
        faces = []
        for x, y, fw, fh, *_ in ([] if detections is None else detections):
            if fw / w < MIN_FACE_WIDTH:
                continue
            box = (float(max(x / w, 0.0)), float(max(y / h, 0.0)), float(min((x + fw) / w, 1.0)), float(min((y + fh) / h, 1.0)))
            faces.append(Face(box, *self._blinks(rgb8, x, y, fw, fh)))
        return faces

    def _blinks(self, rgb8: np.ndarray, x: float, y: float, fw: float, fh: float) -> tuple[float, float]:
        """Blink scores on a padded, upscaled face crop; (0, 0) if no landmarks."""
        h, w = rgb8.shape[:2]
        pad = 0.6 * max(fw, fh)
        x0, y0 = int(max(x - pad, 0)), int(max(y - pad, 0))
        x1, y1 = int(min(x + fw + pad, w)), int(min(y + fh + pad, h))
        crop = cv2.resize(rgb8[y0:y1, x0:x1], (384, round(384 * (y1 - y0) / max(x1 - x0, 1))))
        result = self._landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
        if not result.face_blendshapes:
            return 0.0, 0.0
        scores = {s.category_name: s.score for s in result.face_blendshapes[0]}
        return scores.get("eyeBlinkLeft", 0.0), scores.get("eyeBlinkRight", 0.0)


def _sharpness(gray: np.ndarray, faces: list[Face]) -> float:
    """90th-percentile tile Laplacian variance, comparable across photos.

    Using the sharpest region instead of the global mean keeps intentional
    background blur from being mistaken for a missed focus. Measuring only on
    faces was tried and rejected: smooth skin reads as "blurred".
    """
    # Laplacian variance grows with contrast squared; stretch first so a dark
    # but sharp photo is not mistaken for a blurred one.
    lo, hi = np.percentile(gray, (2, 98))
    norm = np.clip((gray.astype(np.float32) - lo) * (255.0 / max(hi - lo, 1.0)), 0, 255).astype(np.float32)
    lap = cv2.Laplacian(norm, cv2.CV_32F)
    h, w = gray.shape
    th, tw = h // 8, w // 8
    tiles = [lap[y:y + th, x:x + tw].var() for y in range(0, h - th + 1, th) for x in range(0, w - tw + 1, tw)]
    return float(np.percentile(tiles, 90))
