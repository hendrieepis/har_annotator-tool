"""Automatic clip proposals from subject motion and the draggable markers.

Pipeline (static camera assumed):

1. :func:`compute_trajectory` decodes the video once at low resolution, builds a
   median background and, per frame, takes the median x (body centre) and the
   near-foot y of the pixels that differ from it -> the subject's position over
   time (fractions of the frame). Feet are used vertically because they sweep a
   much wider range than the body centre when walking toward/away from camera.
   It does not depend on the markers, so it is cached and reused.
2. :func:`find_passes` walks that trajectory and reports every pass in which the
   subject goes from a direction's *start* line to its *stop* line.

Frame indices use the same pts-based formula as :mod:`video`, so they line up
with the preview and with ffmpeg export.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .markers import DIRECTION_RULES, MarkerSet, start_stop_keys

SMALL_W, SMALL_H = 128, 72     # analysis resolution
DIFF_THRESHOLD = 25            # gray-level difference that counts as motion
MIN_AREA_FRAC = 0.004          # moving area needed to say "subject present"
MAX_GAP = 10                   # interpolate missing frames up to this length
MIN_PASS_FRAMES = 5            # ignore flickers shorter than this
SMOOTH = 5                     # median filter width (frames)
FOOT_QUANTILE = 0.97           # vertical position = near the feet, not mid-body
CACHE_VERSION = 2


class Cancelled(Exception):
    pass


@dataclass
class Trajectory:
    fps: float
    x: np.ndarray   # (n,) fraction of width, NaN when subject absent
    y: np.ndarray   # (n,) fraction of height

    def axis(self, axis: str) -> np.ndarray:
        return self.x if axis == "x" else self.y

    # -- cache ------------------------------------------------------------
    def save(self, path: Path, source: Path) -> None:
        st = source.stat()
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, fps=self.fps, x=self.x, y=self.y,
            sig=np.array([CACHE_VERSION, st.st_size, int(st.st_mtime)]),
        )

    @classmethod
    def load(cls, path: Path, source: Path) -> "Trajectory | None":
        try:
            st = source.stat()
            with np.load(path) as d:
                if list(d["sig"]) != [CACHE_VERSION, st.st_size, int(st.st_mtime)]:
                    return None
                return cls(float(d["fps"]), d["x"], d["y"])
        except (OSError, KeyError, ValueError):
            return None


@dataclass(frozen=True)
class Pass:
    direction: str
    start_frame: int
    end_frame: int


# ---------------------------------------------------------------- trajectory
def compute_trajectory(
    path: str | Path,
    progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Trajectory:
    import av

    path = Path(path)
    frames: dict[int, np.ndarray] = {}
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        tb = float(stream.time_base)
        fps = float(stream.average_rate or stream.base_rate or 30.0)
        total = stream.frames or 0
        for n, frame in enumerate(container.decode(stream)):
            if frame.pts is None:
                continue
            idx = int(round(frame.pts * tb * fps))
            small = frame.reformat(width=SMALL_W, height=SMALL_H, format="gray")
            frames[idx] = small.to_ndarray()
            if n % 50 == 0:
                if should_cancel and should_cancel():
                    raise Cancelled()
                if progress and total:
                    progress(min(0.9, 0.9 * n / total))
    if not frames:
        raise RuntimeError("no video frames could be decoded")

    count = max(frames) + 1
    stack = np.zeros((count, SMALL_H, SMALL_W), np.uint8)
    present = np.zeros(count, bool)
    for idx, arr in frames.items():
        stack[idx] = arr
        present[idx] = True
    sample = stack[present][:: max(1, int(present.sum()) // 200)]
    background = np.median(sample, axis=0).astype(np.int16)

    x = np.full(count, np.nan)
    y = np.full(count, np.nan)
    min_area = MIN_AREA_FRAC * SMALL_W * SMALL_H
    for idx in np.flatnonzero(present):
        mask = np.abs(stack[idx].astype(np.int16) - background) > DIFF_THRESHOLD
        if mask.sum() < min_area:
            continue
        cols = np.cumsum(mask.sum(axis=0))
        rows = np.cumsum(mask.sum(axis=1))
        x[idx] = (np.searchsorted(cols, cols[-1] / 2) + 0.5) / SMALL_W
        y[idx] = (np.searchsorted(rows, rows[-1] * FOOT_QUANTILE) + 0.5) / SMALL_H
    if progress:
        progress(1.0)
    return Trajectory(fps, _clean(x), _clean(y))


def _clean(v: np.ndarray) -> np.ndarray:
    """Fill short gaps linearly, then median-smooth (long gaps stay NaN)."""
    v = v.copy()
    n = len(v)
    ok = ~np.isnan(v)
    if ok.sum() < 2:
        return v
    idx = np.arange(n)
    filled = np.interp(idx, idx[ok], v[ok])
    # length of the NaN run each frame belongs to
    run = np.zeros(n, int)
    i = 0
    while i < n:
        if ok[i]:
            i += 1
            continue
        j = i
        while j < n and not ok[j]:
            j += 1
        run[i:j] = j - i
        i = j
    interp_ok = (~ok) & (run <= MAX_GAP) & (idx > idx[ok][0]) & (idx < idx[ok][-1])
    v[interp_ok] = filled[interp_ok]
    out = v.copy()
    half = SMOOTH // 2
    for i in range(n):
        if np.isnan(v[i]):
            continue
        w = v[max(0, i - half): i + half + 1]
        out[i] = np.nanmedian(w)
    return out


# -------------------------------------------------------------------- passes
def find_passes(
    traj: Trajectory, markers: MarkerSet, directions
) -> list[Pass]:
    """All start-line -> stop-line passes for the given directions, in time order."""
    passes: list[Pass] = []
    for d in directions:
        keys = start_stop_keys(d, markers.flip)
        if keys is None:
            continue
        axis, _ = DIRECTION_RULES[d]
        passes += _passes_for(d, traj.axis(axis), markers.get(keys[0]),
                              markers.get(keys[1]))
    passes.sort(key=lambda p: p.start_frame)
    return _apply_roll(passes, traj, markers)


def _apply_roll(passes: list[Pass], traj: Trajectory, markers: MarkerSet) -> list[Pass]:
    """Extend each pass by pre/post roll (seconds), never into a neighbour."""
    pre = int(round(markers.pre_roll * traj.fps))
    post = int(round(markers.post_roll * traj.fps))
    if not (pre or post):
        return passes
    last = len(traj.x) - 1
    out: list[Pass] = []
    for i, ps in enumerate(passes):
        lo = out[-1].end_frame + 1 if out else 0
        hi = passes[i + 1].start_frame - 1 if i + 1 < len(passes) else last
        # a following pass may itself start earlier by its own pre-roll
        hi = max(ps.end_frame, hi - pre)
        out.append(Pass(
            ps.direction,
            max(lo, ps.start_frame - pre),
            min(hi, ps.end_frame + post),
        ))
    return out


def _passes_for(direction: str, p: np.ndarray, start: float, stop: float) -> list[Pass]:
    out: list[Pass] = []
    forward = stop > start          # moving toward larger coordinates
    s_frame: int | None = None
    prev = np.nan
    for t, cur in enumerate(p):
        if np.isnan(cur):           # lost the subject: abandon any open pass
            s_frame = None
            prev = np.nan
            continue
        if not np.isnan(prev):
            if forward:
                crossed_start = prev < start <= cur
                crossed_stop = prev < stop <= cur
                fell_back = cur < start
            else:
                crossed_start = prev > start >= cur
                crossed_stop = prev > stop >= cur
                fell_back = cur > start
            if crossed_start:
                s_frame = t
            elif s_frame is not None and crossed_stop:
                if t - s_frame >= MIN_PASS_FRAMES:
                    out.append(Pass(direction, s_frame, t))
                s_frame = None
            elif s_frame is not None and fell_back:
                s_frame = None
        prev = cur
    return out
