"""Group bursts/near-duplicates and decide which photos to keep.

Reasons are user-facing text, so they stay in Portuguese.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import imagehash
import numpy as np

from .analyze import Analysis

BURST_MAX_GAP = dt.timedelta(seconds=4)
DUPLICATE_HASH_DISTANCE = 12  # of 64 bits
# A retake of the same pose a few seconds later (group photos): a longer gap,
# so it must look closer than a burst frame does.
RETAKE_MAX_GAP = dt.timedelta(seconds=20)
RETAKE_HASH_DISTANCE = 8
# Fractions of the median sharpness for the same file format. Close-ups with
# smooth skin and soft backgrounds score low without being blurred, so only
# extreme cases are rejected; the borderline band goes to human review.
BLUR_REJECT_BELOW = 0.15
BLUR_REVIEW_BELOW = 0.35
MAIN_FACE_MIN_WIDTH = 0.10
MAX_CLIPPED_HIGHLIGHTS = 0.25
MIN_MEDIAN_LUMA = 0.03


@dataclass
class Decision:
    path: Path
    keep: bool
    score: float
    group: int
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # kept, but worth a human look


def group_bursts(paths: list[Path], analyses: dict[Path, Analysis],
                 times: dict[Path, dt.datetime | None]) -> list[list[Path]]:
    """Consecutive shots that look alike form a group: bursts (within
    BURST_MAX_GAP) and retakes of the same pose (within RETAKE_MAX_GAP, closer look).

    Without a capture time there is no order to trust, so the photo is
    compared against every existing group instead of only the previous one.
    """
    ordered = sorted(paths, key=lambda p: (times[p] or dt.datetime.max, p.name))
    hashes = {p: imagehash.hex_to_hash(analyses[p].phash) for p in paths}
    groups: list[list[Path]] = []
    for path in ordered:
        limit = DUPLICATE_HASH_DISTANCE
        if times[path] is None:
            candidates = groups
        else:
            last = groups[-1][-1] if groups else None
            gap = times[path] - times[last] if last is not None and times[last] is not None else None
            candidates = groups[-1:] if gap is not None and gap <= RETAKE_MAX_GAP else []
            if gap is not None and gap > BURST_MAX_GAP:
                limit = RETAKE_HASH_DISTANCE
        match = next((g for g in candidates if hashes[path] - hashes[g[-1]] <= limit), None)
        if match is not None:
            match.append(path)
        else:
            groups.append([path])
    return groups


def decide(paths: list[Path], analyses: dict[Path, Analysis],
           times: dict[Path, dt.datetime | None]) -> list[Decision]:
    # HEIC/JPEG come sharpened by the phone, RAW does not: compare within format.
    medians = {}
    for ext in {p.suffix.lower() for p in paths}:
        values = [analyses[p].sharpness for p in paths if p.suffix.lower() == ext]
        medians[ext] = float(np.median(values)) or 1.0
    decisions: list[Decision] = []
    for group_id, group in enumerate(group_bursts(paths, analyses, times)):
        candidates = []
        for path in group:
            a = analyses[path]
            median_sharpness = medians[path.suffix.lower()]
            reasons = _hard_rejects(a, median_sharpness)
            score = _score(a, median_sharpness)
            flags = (["Possivelmente tremida — revisar"]
                     if not reasons and a.sharpness < BLUR_REVIEW_BELOW * median_sharpness else [])
            decisions.append(d := Decision(path, keep=not reasons, score=score, group=group_id,
                                           reasons=reasons, flags=flags))
            if d.keep:
                candidates.append(d)
        if len(candidates) > 1:
            best = max(candidates, key=lambda d: d.score)
            for d in candidates:
                if d is not best:
                    d.keep = False
                    d.reasons.append(f"Repetida — melhor da sequência: {best.path.name}")
    return decisions


def _hard_rejects(a: Analysis, median_sharpness: float) -> list[str]:
    reasons = []
    if a.sharpness < BLUR_REJECT_BELOW * median_sharpness:
        reasons.append("Tremida ou fora de foco")
    main = a.main_face
    if main and main.width >= MAIN_FACE_MIN_WIDTH and main.eyes_closed:
        reasons.append("Olhos fechados (pessoa principal)")
    if a.clipped_highlights > MAX_CLIPPED_HIGHLIGHTS:
        reasons.append("Estourada (sem recuperação)")
    if a.median_luma < MIN_MEDIAN_LUMA:
        reasons.append("Escura demais (sem recuperação)")
    return reasons


def _score(a: Analysis, median_sharpness: float) -> float:
    sharp = min(a.sharpness / median_sharpness, 3.0)
    open_eyes = sum(1 for f in a.faces if not f.eyes_closed)
    closed = sum(1 for f in a.faces if f.eyes_closed)
    exposure_penalty = abs(a.median_luma - 0.45) + 2 * a.clipped_highlights
    return sharp + 0.3 * open_eyes - 0.6 * closed - exposure_penalty
