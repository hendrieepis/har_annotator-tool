"""Small window to watch exported clips inside the app (no external player)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from har_annotator.ui.player import VideoPlayerWidget


class ClipPlayerDialog(QDialog):
    """Plays the clips of a list one by one; can ask to delete the current one."""

    deleteRequested = Signal(str)  # file name of the clip to delete

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clip player")
        self.resize(900, 620)
        self._clips: list[Path] = []
        self._row = 0

        self.title = QLabel()
        self.title.setStyleSheet("font-weight:bold; font-size:14px;")
        self.player = VideoPlayerWidget()
        self.player.playbackStopped.connect(self._on_stopped)
        self.chk_loop = QCheckBox("Loop")
        self.chk_loop.setChecked(True)
        self.chk_next = QCheckBox("Play next clip automatically")
        self.btn_prev = QPushButton("◀ Previous clip")
        self.btn_next = QPushButton("Next clip ▶")
        self.btn_delete = QPushButton("🗑 Delete this clip (Del)")
        self.btn_delete.setToolTip(
            "Delete the file and remove it from the exported list"
        )
        self.btn_prev.clicked.connect(lambda: self.show_clip(self._row - 1))
        self.btn_next.clicked.connect(lambda: self.show_clip(self._row + 1))
        self.btn_delete.clicked.connect(self._ask_delete)

        row = QHBoxLayout()
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_next)
        row.addWidget(self.chk_loop)
        row.addWidget(self.chk_next)
        row.addStretch(1)
        row.addWidget(self.btn_delete)
        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addWidget(self.player, 1)
        lay.addLayout(row)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.player.toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.player.step(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.player.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._ask_delete)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self, activated=lambda: self.show_clip(self._row - 1))
        QShortcut(QKeySequence(Qt.Key.Key_Down), self, activated=lambda: self.show_clip(self._row + 1))

    # ----------------------------------------------------------------- API
    def open_clips(self, clips: list[Path], row: int = 0) -> None:
        self._clips = list(clips)
        self.show_clip(row)

    def release_current(self) -> None:
        """Pause and close the open file (needed before it can be deleted)."""
        self.player.stop()
        if self.player.reader is not None:
            self.player.reader.release()
            self.player.reader = None

    def reload_current(self) -> None:
        self.show_clip(self._row)

    def remove_clip(self, name: str) -> None:
        """Drop a (deleted) clip from the list and continue with its neighbour."""
        names = [c.name for c in self._clips]
        if name not in names:
            return
        i = names.index(name)
        self.player.stop()
        if self.player.reader is not None:   # release the file before it is deleted
            self.player.reader.release()
            self.player.reader = None
        del self._clips[i]
        if not self._clips:
            self.close()
            return
        self.show_clip(min(i, len(self._clips) - 1))

    def show_clip(self, row: int) -> None:
        if not self._clips:
            return
        row = max(0, min(row, len(self._clips) - 1))
        self._row = row
        path = self._clips[row]
        self.title.setText(f"{path.name}    ({row + 1}/{len(self._clips)})")
        self.btn_prev.setEnabled(row > 0)
        self.btn_next.setEnabled(row < len(self._clips) - 1)
        try:
            self.player.load(path)
        except Exception as exc:  # missing / unreadable file
            self.title.setText(f"{path.name}: cannot open ({exc})")
            return
        self.player.play()

    # ------------------------------------------------------------ internals
    def _on_stopped(self, finished: bool) -> None:
        if not finished:
            return
        if self.chk_next.isChecked() and self._row < len(self._clips) - 1:
            self.show_clip(self._row + 1)
        elif self.chk_loop.isChecked():
            self.player.seek(0)
            self.player.play()

    def _ask_delete(self) -> None:
        if self._clips:
            self.deleteRequested.emit(self._clips[self._row].name)

    def closeEvent(self, event) -> None:
        self.player.stop()
        if self.player.reader is not None:
            self.player.reader.release()
            self.player.reader = None
        super().closeEvent(event)
