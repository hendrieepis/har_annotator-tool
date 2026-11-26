"""Frame-accurate preview decoding via PyAV.

Used only for *displaying* frames in the UI. Actual clip cutting is done by
ffmpeg (see :mod:`exporter`) so output quality is preserved exactly.

PyAV is used instead of OpenCV because OpenCV's GUI build links its own copy of
Qt, which clashes with PySide6 inside a single process. PyAV has no such
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

# When scrubbing forward we keep decoding from the open generator; only re-seek
# (which costs a keyframe jump + decode) when going backwards or jumping far.
_FORWARD_REUSE_WINDOW = 300


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    frame_count: int
    fps: float
    width: int
    height: int

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


class VideoReader:
    """Random-access frame reader returning BGR ndarrays."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._container = av.open(str(self.path))
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        self._time_base = float(self._stream.time_base)

        fps = float(self._stream.average_rate or self._stream.base_rate or 30.0)
        frame_count = self._stream.frames
        if not frame_count:
            if self._stream.duration:
                dur = self._stream.duration * self._time_base
            elif self._container.duration:
                dur = self._container.duration / av.time_base
            else:
                dur = 0.0
            frame_count = int(round(dur * fps))
        cc = self._stream.codec_context
        self.info = VideoInfo(self.path, frame_count, fps, cc.width, cc.height)

        self._gen = None
        self._cursor: int | None = None  # index of the next frame _gen will yield

    # ------------------------------------------------------------------
    def _frames(self):
        for frame in self._container.decode(self._stream):
            if frame.pts is None:
                continue
            idx = int(round(frame.pts * self._time_base * self.info.fps))
            yield idx, frame

    def _seek(self, index: int) -> None:
        target_sec = index / self.info.fps
        offset = int(target_sec / self._time_base)
        self._container.seek(
            offset, stream=self._stream, backward=True, any_frame=False
        )
        self._gen = self._frames()
        self._cursor = None

    def get_frame(self, index: int) -> np.ndarray | None:
        """Return the BGR frame at *index*, or ``None`` if unavailable."""
        index = max(0, min(index, self.info.frame_count - 1))
        need_seek = (
            self._gen is None
            or self._cursor is None
            or index < self._cursor
            or index > self._cursor + _FORWARD_REUSE_WINDOW
        )
        if need_seek:
            self._seek(index)

        result = None
        for idx, frame in self._gen:
            self._cursor = idx + 1
            if idx >= index:
                result = frame
                break
        if result is None:
            return None
        # to_ndarray(format="bgr24") keeps parity with the rest of the code.
        return result.to_ndarray(format="bgr24")

    def release(self) -> None:
        if self._container is not None:
            self._container.close()
            self._container = None

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
