"""Background ffmpeg export so the UI stays responsive.

Exports a *batch* of clips sequentially. Each clip that finishes is reported
individually (``one_done``) so the session can move it from pending to exported
and persist immediately — if the app dies mid-batch, the clips already rendered
are safely recorded.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from har_annotator.core.exporter import ExportRequest, export_clip


class BatchExportWorker(QThread):
    # (done_count, total, current_clip_fraction)
    progress = Signal(int, int, float)
    one_done = Signal(int)        # clip index that just finished
    finished_all = Signal()
    failed = Signal(str)          # error message (batch stops on first failure)

    def __init__(self, jobs: list[tuple[int, ExportRequest]], parent=None):
        super().__init__(parent)
        self.jobs = jobs

    def run(self) -> None:
        total = len(self.jobs)
        for done, (index, request) in enumerate(self.jobs):
            try:
                export_clip(
                    request,
                    progress=lambda f, d=done: self.progress.emit(d, total, f),
                )
            except Exception as exc:  # surface ffmpeg/IO error, keep prior clips
                self.failed.emit(f"{request.output.name}: {exc}")
                return
            self.one_done.emit(index)
        self.finished_all.emit()
