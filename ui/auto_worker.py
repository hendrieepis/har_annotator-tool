"""Background motion analysis so the UI stays responsive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from har_annotator.core.autoclip import Cancelled, Trajectory, compute_trajectory


class TrajectoryWorker(QThread):
    progress = Signal(int)          # 0..100
    done = Signal(object)           # Trajectory
    failed = Signal(str)

    def __init__(self, source: Path, cache: Path, parent=None):
        super().__init__(parent)
        self.source = source
        self.cache = cache
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            traj = Trajectory.load(self.cache, self.source)
            if traj is None:
                traj = compute_trajectory(
                    self.source,
                    progress=lambda f: self.progress.emit(int(f * 100)),
                    should_cancel=lambda: self._cancel,
                )
                try:
                    traj.save(self.cache, self.source)
                except OSError:
                    pass  # cache is optional
            self.done.emit(traj)
        except Cancelled:
            self.failed.emit("Cancelled.")
        except Exception as exc:
            self.failed.emit(str(exc))
