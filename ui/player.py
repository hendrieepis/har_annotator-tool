"""Video preview widget: frame display, transport, scrubber, frame stepping."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from har_annotator.core.video import VideoReader


def _to_pixmap(frame) -> QPixmap:
    # frame is BGR; reverse the channel axis to RGB for Qt.
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    h, w, _ = rgb.shape
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


def _fmt_time(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:06.3f}"


class VideoPlayerWidget(QWidget):
    """Owns a :class:`VideoReader` and exposes the current frame index."""

    frameChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader: VideoReader | None = None
        self._frame_index = 0
        self._start_marker: int | None = None
        self._end_marker: int | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_playback)

        self._build_ui()
        self._set_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.display = QLabel("Open a folder and select a video to begin.")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setMinimumSize(640, 360)
        self.display.setStyleSheet("background:#111; color:#888;")
        self.display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)

        self.frame_spin = QSpinBox()
        self.frame_spin.setMaximum(0)
        self.frame_spin.valueChanged.connect(self.seek)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setMinimumWidth(180)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.clicked.connect(self.toggle_play)

        controls = QHBoxLayout()
        for text, slot in [
            ("⏮ -10", lambda: self.step(-10)),
            ("◀ -1", lambda: self.step(-1)),
            ("+1 ▶", lambda: self.step(1)),
            ("+10 ⏭", lambda: self.step(10)),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            controls.addWidget(b)
        controls.addWidget(self.btn_play)
        controls.addStretch(1)
        controls.addWidget(QLabel("Frame:"))
        controls.addWidget(self.frame_spin)
        controls.addWidget(self.time_label)

        layout = QVBoxLayout(self)
        layout.addWidget(self.display, 1)
        layout.addWidget(self.slider)
        layout.addLayout(controls)

    def _set_enabled(self, on: bool) -> None:
        self.slider.setEnabled(on)
        self.frame_spin.setEnabled(on)
        self.btn_play.setEnabled(on)

    # -------------------------------------------------------------- public
    def load(self, path) -> VideoReader:
        self.stop()
        if self.reader is not None:
            self.reader.release()
        self.reader = VideoReader(path)
        info = self.reader.info
        last = max(info.frame_count - 1, 0)

        self.slider.blockSignals(True)
        self.slider.setRange(0, last)
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        self.frame_spin.blockSignals(True)
        self.frame_spin.setRange(0, last)
        self.frame_spin.setValue(0)
        self.frame_spin.blockSignals(False)

        self._start_marker = None
        self._end_marker = None
        self._set_enabled(True)
        self.seek(0)
        return self.reader

    @property
    def frame_index(self) -> int:
        return self._frame_index

    def set_markers(self, start: int | None, end: int | None) -> None:
        self._start_marker = start
        self._end_marker = end

    def seek(self, index: int) -> None:
        if self.reader is None:
            return
        frame = self.reader.get_frame(index)
        if frame is None:
            return
        self._frame_index = index
        self._render(frame)
        self._sync_controls(index)
        self.frameChanged.emit(index)

    def step(self, delta: int) -> None:
        self.seek(self._frame_index + delta)

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.stop()
        else:
            self.play()

    def play(self) -> None:
        if self.reader is None:
            return
        fps = self.reader.info.fps or 30.0
        self._timer.start(int(1000 / fps))
        self.btn_play.setText("⏸ Pause")

    def stop(self) -> None:
        self._timer.stop()
        self.btn_play.setText("▶ Play")

    # ------------------------------------------------------------- internals
    def _advance_playback(self) -> None:
        if self.reader is None:
            return
        if self._frame_index >= self.reader.info.frame_count - 1:
            self.stop()
            return
        self.seek(self._frame_index + 1)

    def _render(self, frame) -> None:
        pix = _to_pixmap(frame)
        self.display.setPixmap(
            pix.scaled(
                self.display.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _sync_controls(self, index: int) -> None:
        for w in (self.slider, self.frame_spin):
            w.blockSignals(True)
            w.setValue(index)
            w.blockSignals(False)
        if self.reader is not None:
            info = self.reader.info
            fps = info.fps or 30.0
            self.time_label.setText(
                f"{_fmt_time(index / fps)} / {_fmt_time(info.duration)}"
                f"   (f{index}/{max(info.frame_count - 1, 0)})"
            )

    def _on_slider(self, value: int) -> None:
        if value != self._frame_index:
            self.seek(value)

    def resizeEvent(self, event):  # keep current frame fitted on resize
        super().resizeEvent(event)
        if self.reader is not None:
            frame = self.reader.get_frame(self._frame_index)
            if frame is not None:
                self._render(frame)
