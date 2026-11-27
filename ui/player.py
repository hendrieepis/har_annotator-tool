"""Video preview widget: frame display, transport, scrubber, frame stepping."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen, QPixmap
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

from har_annotator.core.markers import MarkerSet
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


# marker key -> (axis, colour). Low/high lines get fixed, distinct colours.
_LINE_STYLE = {
    "x_left": ("x", QColor("#00c8ff")),
    "x_right": ("x", QColor("#ffb300")),
    "y_top": ("y", QColor("#00c8ff")),
    "y_bottom": ("y", QColor("#ffb300")),
}
_GRAB_PX = 9  # how close (px) the mouse must be to grab a line


class FrameView(QWidget):
    """Shows the current frame and the draggable start/stop marker lines.

    Lines are stored on a shared :class:`MarkerSet` (fractions of the frame), so
    they stay glued to the picture when the window is resized. Drag a line with
    the left mouse button; ``markersChanged`` fires continuously while dragging
    and ``markersReleased`` once when the button is let go.
    """

    markersChanged = Signal()
    markersReleased = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._markers: MarkerSet | None = None
        self._labels: dict[str, str] = {}   # marker key -> caption
        self._visible = True
        self._drag: str | None = None
        self._hover: str | None = None
        self._locked = False
        self._placeholder = "Open a folder and select a video to begin."
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    # -- state ------------------------------------------------------------
    def set_pixmap(self, pix: QPixmap | None) -> None:
        self._pix = pix
        self.update()

    def set_overlay(self, markers: MarkerSet | None, labels: dict[str, str]) -> None:
        self._markers = markers
        self._labels = labels
        self.update()

    def set_markers_visible(self, on: bool) -> None:
        self._visible = on
        self.update()

    def set_locked(self, locked: bool) -> None:
        """While locked (auto clip running) lines cannot be dragged."""
        self._locked = locked
        self._drag = None
        self._hover = None
        self.unsetCursor()
        self.update()

    # -- geometry ---------------------------------------------------------
    def _frame_rect(self) -> QRectF:
        if self._pix is None or self._pix.isNull():
            return QRectF()
        w, h = self._pix.width(), self._pix.height()
        scale = min(self.width() / w, self.height() / h)
        fw, fh = w * scale, h * scale
        return QRectF((self.width() - fw) / 2, (self.height() - fh) / 2, fw, fh)

    def _active_keys(self) -> list[str]:
        return [k for k in self._labels if k in _LINE_STYLE]

    def _line_pos(self, key: str, r: QRectF) -> float:
        axis, _ = _LINE_STYLE[key]
        v = self._markers.get(key)
        return r.left() + v * r.width() if axis == "x" else r.top() + v * r.height()

    def _hit(self, pos: QPointF) -> str | None:
        if not (self._visible and self._markers) or self._locked:
            return None
        r = self._frame_rect()
        if r.isNull():
            return None
        best, best_d = None, _GRAB_PX + 1
        for key in self._active_keys():
            axis, _ = _LINE_STYLE[key]
            d = abs((pos.x() if axis == "x" else pos.y()) - self._line_pos(key, r))
            if d < best_d:
                best, best_d = key, d
        return best

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111"))
        r = self._frame_rect()
        if r.isNull():
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        if self._visible and self._markers:
            for key in self._active_keys():
                self._paint_line(p, key, r)

    def _paint_line(self, p: QPainter, key: str, r: QRectF) -> None:
        axis, color = _LINE_STYLE[key]
        pos = self._line_pos(key, r)
        active = key in (self._drag, self._hover)
        pen = QPen(color, 3 if active else 2)
        pen.setStyle(Qt.PenStyle.SolidLine if active else Qt.PenStyle.DashLine)
        p.setPen(pen)
        if axis == "x":
            p.drawLine(QPointF(pos, r.top()), QPointF(pos, r.bottom()))
            grip = QRectF(pos - 7, r.center().y() - 18, 14, 36)
        else:
            p.drawLine(QPointF(r.left(), pos), QPointF(r.right(), pos))
            grip = QRectF(r.center().x() - 18, pos - 7, 36, 14)
        # grip = visible "handle" so it is obvious the line can be dragged
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(grip, 4, 4)

        text = self._labels.get(key, "")
        if text:
            fm = QFontMetrics(p.font())
            tw, th = fm.horizontalAdvance(text) + 12, fm.height() + 6
            if axis == "x":
                x = min(max(pos + 6, r.left()), r.right() - tw)
                box = QRectF(x, r.top() + 6, tw, th)
            else:
                y = min(max(pos + 6, r.top()), r.bottom() - th)
                box = QRectF(r.left() + 6, y, tw, th)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(color)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- mouse ------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = self._hit(e.position())
            if self._drag:
                self._apply_drag(e.position())
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag:
            self._apply_drag(e.position())
            return
        hit = self._hit(e.position())
        if hit != self._hover:
            self._hover = hit
            self.update()
        if hit:
            axis, _ = _LINE_STYLE[hit]
            self.setCursor(
                Qt.CursorShape.SizeHorCursor if axis == "x"
                else Qt.CursorShape.SizeVerCursor
            )
            self.setToolTip("Drag to move this marker")
        else:
            self.unsetCursor()
            self.setToolTip("")

    def mouseReleaseEvent(self, e) -> None:
        if self._drag and e.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.update()
            self.markersReleased.emit()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, _e) -> None:
        if self._hover and not self._drag:
            self._hover = None
            self.update()

    def _apply_drag(self, pos: QPointF) -> None:
        r = self._frame_rect()
        if r.isNull() or not (self._drag and self._markers):
            return
        axis, _ = _LINE_STYLE[self._drag]
        v = (pos.x() - r.left()) / r.width() if axis == "x" else (
            (pos.y() - r.top()) / r.height()
        )
        self._markers.move(self._drag, v)
        self.update()
        self.markersChanged.emit()


class VideoPlayerWidget(QWidget):
    """Owns a :class:`VideoReader` and exposes the current frame index."""

    frameChanged = Signal(int)
    markersEdited = Signal()   # user finished dragging a marker line
    playbackStopped = Signal(bool)  # True = reached the last frame, False = paused

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader: VideoReader | None = None
        self._frame_index = 0
        self._start_marker: int | None = None
        self._end_marker: int | None = None

        # Optional hook run before playback starts; return False to veto it
        # (e.g. while a background analysis must finish first).
        self.play_guard = None
        self._play_text = "▶ Play"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_playback)

        self._build_ui()
        self._set_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.display = FrameView()
        self.display.markersReleased.connect(self.markersEdited)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)

        self.frame_spin = QSpinBox()
        self.frame_spin.setMaximum(0)
        self.frame_spin.valueChanged.connect(self.seek)

        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setMinimumWidth(180)

        self.btn_play = QPushButton(self._play_text)
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

    def set_marker_overlay(
        self, markers: MarkerSet | None, labels: dict[str, str]
    ) -> None:
        """Show draggable start/stop lines. *labels* maps marker key -> caption."""
        self.display.set_overlay(markers, labels)

    def set_markers_visible(self, on: bool) -> None:
        self.display.set_markers_visible(on)

    def set_markers_locked(self, locked: bool) -> None:
        self.display.set_locked(locked)

    def set_play_text(self, text: str) -> None:
        self._play_text = text
        if not self._timer.isActive():
            self.btn_play.setText(text)

    @property
    def is_playing(self) -> bool:
        return self._timer.isActive()

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
        if self.play_guard is not None and not self.play_guard():
            return
        fps = self.reader.info.fps or 30.0
        self._timer.start(int(1000 / fps))
        self.btn_play.setText("⏸ Pause")

    def stop(self, finished: bool = False) -> None:
        was_playing = self._timer.isActive()
        self._timer.stop()
        self.btn_play.setText(self._play_text)
        if was_playing:
            self.playbackStopped.emit(finished)

    # ------------------------------------------------------------- internals
    def _advance_playback(self) -> None:
        if self.reader is None:
            return
        if self._frame_index >= self.reader.info.frame_count - 1:
            self.stop(finished=True)
            return
        self.seek(self._frame_index + 1)

    def _render(self, frame) -> None:
        self.display.set_pixmap(_to_pixmap(frame))

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

