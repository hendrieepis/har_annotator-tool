"""Frame-accurate clip cutting via ffmpeg.

The source recordings are constant-frame-rate H.264. To guarantee the start and
end land on the exact operator-chosen frames *and* keep resolution / fps /
orientation / visual quality, we re-encode with x264 at a (configurable)
visually-lossless CRF rather than doing a keyframe-aligned stream copy.

``-ss`` is placed *before* ``-i`` for a fast accurate input seek, and
``-frames:v N`` guarantees an exact, inclusive frame count.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityPreset:
    name: str
    crf: int
    preset: str
    description: str


QUALITY_PRESETS: dict[str, QualityPreset] = {
    "visually_lossless": QualityPreset(
        "visually_lossless", 17, "slow",
        "Visually lossless (CRF 17) — recommended, indistinguishable from source",
    ),
    "high": QualityPreset(
        "high", 14, "slow",
        "Very high (CRF 14) — larger files, extra headroom",
    ),
    "lossless": QualityPreset(
        "lossless", 0, "medium",
        "Mathematically lossless (CRF 0) — exact pixels, very large files",
    ),
}
DEFAULT_QUALITY = "visually_lossless"


@dataclass
class ExportRequest:
    source: Path
    output: Path
    start_frame: int
    end_frame: int          # inclusive
    fps: float
    quality: str = DEFAULT_QUALITY
    keep_audio: bool = False

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame + 1


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def build_command(req: ExportRequest) -> list[str]:
    if req.frame_count <= 0:
        raise ValueError("end frame must be >= start frame")
    preset = QUALITY_PRESETS.get(req.quality, QUALITY_PRESETS[DEFAULT_QUALITY])
    start_time = req.start_frame / req.fps

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.6f}",
        "-i", str(req.source),
        "-frames:v", str(req.frame_count),
        "-c:v", "libx264",
        "-crf", str(preset.crf),
        "-preset", preset.preset,
        "-pix_fmt", "yuv420p",
        # carry source rotation/display metadata through to the clip
        "-map_metadata", "0",
        "-movflags", "+faststart",
    ]
    if req.keep_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd.append(str(req.output))
    return cmd


def export_clip(req: ExportRequest, progress=None) -> None:
    """Run ffmpeg synchronously.

    *progress* is an optional callable receiving a float in ``[0, 1]``. Intended
    to be driven from a worker thread (see the UI's export worker).
    """
    req.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(req)
    # Stream ffmpeg's machine-readable progress so the UI can show a bar.
    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    total = req.frame_count
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if progress and line.startswith("frame="):
            try:
                done = int(line.split("=", 1)[1])
                progress(min(done / total, 1.0))
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode}):\n{err[-2000:]}")
    if progress:
        progress(1.0)
