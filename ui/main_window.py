"""Main application window: folder browser, preview, marking & batch export.

Workflow is split into two phases:

* **Mark** — Set Start (I) then Set End (O) adds a *pending* clip (named &
  numbered automatically) to a list, auto-persisted to disk. No rendering yet.
* **Export** — "Export All" / "Export Selected" render pending clips to physical
  files via ffmpeg in the background, moving each to the "exported" list as it
  finishes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from har_annotator.core.exporter import (
    DEFAULT_QUALITY,
    QUALITY_PRESETS,
    ExportRequest,
    ffmpeg_available,
)
from har_annotator.core.naming import FilenameSpec
from har_annotator.core.session import (
    AnnotationSession,
    ClipRecord,
    counts_per_direction,
)
from har_annotator.ui.export_worker import BatchExportWorker
from har_annotator.ui.player import VideoPlayerWidget

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
DEFAULT_CHECKPOINT_N = 5


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HAR Dataset Annotator")
        self.resize(1320, 780)

        self.folder: Path | None = None
        self.output_dir: Path | None = None
        self.session: AnnotationSession | None = None
        self.start_frame: int | None = None
        self.end_frame: int | None = None
        self._worker: BatchExportWorker | None = None

        self._build_ui()
        self._install_shortcuts()
        if not ffmpeg_available():
            QMessageBox.critical(
                self, "ffmpeg not found",
                "ffmpeg is required for exporting clips but was not found on PATH.",
            )

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        # ---- left: folder + video list
        self.btn_open = QPushButton("📂 Open Folder…")
        self.btn_open.clicked.connect(self.choose_folder)
        self.video_list = QListWidget()
        self.video_list.currentRowChanged.connect(self._on_video_selected)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(self.btn_open)
        ll.addWidget(QLabel("Source videos:"))
        ll.addWidget(self.video_list, 1)

        # ---- center: player
        self.player = VideoPlayerWidget()
        self.player.frameChanged.connect(self._on_frame_changed)

        mark_row = QHBoxLayout()
        self.btn_start = QPushButton("⟦ Set Start (I)")
        self.btn_start.clicked.connect(self.mark_start)
        self.btn_end = QPushButton("Set End (O) → add to pending ⟧")
        self.btn_end.clicked.connect(self.mark_end)
        mark_row.addWidget(self.btn_start)
        mark_row.addWidget(self.btn_end)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.addWidget(self.player, 1)
        cl.addLayout(mark_row)

        # ---- right
        right = self._build_right_panel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([240, 720, 360])

        root = QVBoxLayout(self)
        root.addWidget(splitter)
        self.status = QLabel("Ready.")
        root.addWidget(self.status)

    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        right.setMinimumWidth(340)
        rl = QVBoxLayout(right)

        # source info
        info_box = QGroupBox("Source")
        info_form = QFormLayout(info_box)
        self.lbl_source = QLabel("—")
        self.lbl_source.setWordWrap(True)
        self.lbl_dirs = QLabel("—")
        self.lbl_outdir = QLabel("—")
        self.lbl_outdir.setWordWrap(True)
        info_form.addRow("File:", self.lbl_source)
        info_form.addRow("Directions:", self.lbl_dirs)
        info_form.addRow("Output:", self.lbl_outdir)
        rl.addWidget(info_box)

        # current mark in progress
        mark_box = QGroupBox("Current mark")
        mf = QFormLayout(mark_box)
        self.lbl_target = QLabel("—")
        self.lbl_target.setWordWrap(True)
        self.lbl_start = QLabel("not set")
        self.lbl_end = QLabel("not set")
        self.lbl_duration = QLabel("—")
        mf.addRow("Next will be:", self.lbl_target)
        mf.addRow("Start frame:", self.lbl_start)
        mf.addRow("End frame:", self.lbl_end)
        mf.addRow("Length:", self.lbl_duration)
        rl.addWidget(mark_box)

        # pending list + export controls
        pend_box = QGroupBox("Pending clips (marked, not yet exported)")
        pv = QVBoxLayout(pend_box)
        self.pending_list = QListWidget()
        self.pending_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        pv.addWidget(self.pending_list, 1)

        undo_row = QHBoxLayout()
        self.btn_undo_mark = QPushButton("↩ Undo mark (Ctrl+Z)")
        self.btn_undo_mark.clicked.connect(self.undo_last_mark)
        self.btn_redo_mark = QPushButton("Redo mark (Ctrl+Y) ↪")
        self.btn_redo_mark.clicked.connect(self.redo_last_mark)
        undo_row.addWidget(self.btn_undo_mark)
        undo_row.addWidget(self.btn_redo_mark)
        pv.addLayout(undo_row)

        export_row = QHBoxLayout()
        self.btn_export_all = QPushButton("⏏ Export All (S)")
        self.btn_export_all.setStyleSheet("font-weight:bold; padding:6px;")
        self.btn_export_all.clicked.connect(self.export_all)
        self.btn_export_selected = QPushButton("Export Selected")
        self.btn_export_selected.clicked.connect(self.export_selected)
        export_row.addWidget(self.btn_export_all)
        export_row.addWidget(self.btn_export_selected)
        pv.addLayout(export_row)

        chk_row = QHBoxLayout()
        self.chk_autoexport = QCheckBox("Auto-export every")
        self.chk_autoexport.setChecked(True)
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 999)
        self.spin_n.setValue(DEFAULT_CHECKPOINT_N)
        chk_row.addWidget(self.chk_autoexport)
        chk_row.addWidget(self.spin_n)
        chk_row.addWidget(QLabel("marks"))
        chk_row.addStretch(1)
        pv.addLayout(chk_row)

        self.quality_combo = QComboBox()
        for key, preset in QUALITY_PRESETS.items():
            self.quality_combo.addItem(preset.description, key)
        self.quality_combo.setCurrentIndex(
            list(QUALITY_PRESETS).index(DEFAULT_QUALITY)
        )
        pv.addWidget(self.quality_combo)

        self.export_bar = QProgressBar()
        self.export_bar.setRange(0, 100)
        pv.addWidget(self.export_bar)
        rl.addWidget(pend_box, 1)

        # exported summary
        done_box = QGroupBox("Exported clips")
        dv = QVBoxLayout(done_box)
        self.lbl_counts = QLabel("—")
        self.exported_list = QListWidget()
        dv.addWidget(self.lbl_counts)
        dv.addWidget(self.exported_list, 1)
        rl.addWidget(done_box, 1)

        return right

    def _install_shortcuts(self) -> None:
        def sc(seq, slot):
            QShortcut(QKeySequence(seq), self, activated=slot)

        sc(Qt.Key.Key_Space, self.player.toggle_play)
        sc(Qt.Key.Key_Left, lambda: self.player.step(-1))
        sc(Qt.Key.Key_Right, lambda: self.player.step(1))
        sc("[", lambda: self.player.step(-10))
        sc("]", lambda: self.player.step(10))
        sc("I", self.mark_start)
        sc("O", self.mark_end)
        sc("S", self.export_all)
        sc("Ctrl+Z", self.undo_last_mark)
        sc("Ctrl+Y", self.redo_last_mark)
        sc("Ctrl+Shift+Z", self.redo_last_mark)

    # -------------------------------------------------------------- folder
    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open folder of raw videos")
        if not path:
            return
        self.folder = Path(path)
        self.output_dir = self.folder / "clips"
        self._populate_videos()
        self.status.setText(f"Opened {self.folder}")

    def _populate_videos(self) -> None:
        self.video_list.clear()
        assert self.folder is not None
        videos = sorted(
            p for p in self.folder.iterdir()
            if p.suffix.lower() in VIDEO_EXTS and p.is_file()
        )
        for path in videos:
            item = QListWidgetItem(self._list_label(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.video_list.addItem(item)
        if not videos:
            self.status.setText("No video files found in this folder.")

    def _format_list_label(self, path: Path, session: AnnotationSession) -> str:
        done = len(session.exported)
        pend = len(session.pending)
        tick = "✔" if done else ("…" if pend else "•")
        suffix = f"[{done} done" + (f", {pend} pending]" if pend else "]")
        return f"{tick} {path.name}  {suffix}"

    def _list_label(self, path: Path) -> str:
        try:
            spec = FilenameSpec.parse(path)
        except ValueError:
            return f"⚠ {path.name}  (unrecognised name)"
        session = AnnotationSession.load_or_create(path, self.output_dir, spec)
        return self._format_list_label(path, session)

    # --------------------------------------------------------- selection
    def _on_video_selected(self, row: int) -> None:
        if row < 0:
            return
        if self._worker is not None:
            return  # don't switch source mid-export
        item = self.video_list.item(row)
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            spec = FilenameSpec.parse(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot parse filename", str(exc))
            return
        self.session = AnnotationSession.load_or_create(path, self.output_dir, spec)
        try:
            self.player.load(path)
        except IOError as exc:
            QMessageBox.critical(self, "Cannot open video", str(exc))
            return
        self.start_frame = None
        self.end_frame = None
        self.player.set_markers(None, None)
        self.lbl_source.setText(path.name)
        self.lbl_dirs.setText(" → ".join(spec.directions))
        self.lbl_outdir.setText(str(self.output_dir))
        self.export_bar.setValue(0)
        self._refresh_all()
        if self.session.has_unexported():
            self.status.setText(
                f"Resumed: {len(self.session.pending)} pending clip(s) restored."
            )

    # ------------------------------------------------------------ marking
    def _on_frame_changed(self, index: int) -> None:
        self._update_marker_labels()

    def mark_start(self) -> None:
        if self.session is None:
            return
        self.start_frame = self.player.frame_index
        if self.end_frame is not None and self.end_frame < self.start_frame:
            self.end_frame = None
        self.player.set_markers(self.start_frame, self.end_frame)
        self._update_marker_labels()
        self.status.setText(f"Start frame = {self.start_frame}")

    def mark_end(self) -> None:
        if self.session is None:
            return
        if self.start_frame is None:
            QMessageBox.information(
                self, "Set start first", "Set a start frame (I) before the end."
            )
            return
        end = self.player.frame_index
        if end == self.start_frame:
            QMessageBox.information(
                self,
                "Invalid end",
                "Start and end cannot be at the same time. "
                "Move forward to a later frame before setting the end.",
            )
            return
        if end < self.start_frame:
            QMessageBox.information(
                self, "Invalid end", "End frame is before the start frame."
            )
            return

        record = self.session.add_mark(self.start_frame, end)  # auto-persists
        # reset in-progress markers and advance just past this clip
        self.start_frame = None
        self.end_frame = None
        self.player.set_markers(None, None)
        last = max(self.player.reader.info.frame_count - 1, 0)
        self.player.seek(min(end + 1, last))
        self._refresh_all()
        self._refresh_current_list_item()
        self.status.setText(f"Marked {record.filename}  (pending)")
        self._maybe_checkpoint()

    def undo_last_mark(self) -> None:
        if self.session is None or self._worker is not None:
            return
        if not self.session.pending:
            self.status.setText("No pending mark to undo.")
            return
        record = self.session.remove_last_mark()  # auto-persists
        self._refresh_all()
        self._refresh_current_list_item()
        self.status.setText(f"Removed pending mark {record.filename}")

    def redo_last_mark(self) -> None:
        if self.session is None or self._worker is not None:
            return
        record = self.session.redo_last_mark()  # auto-persists
        if record is None:
            self.status.setText("Nothing to redo.")
            return
        self._refresh_all()
        self._refresh_current_list_item()
        self.status.setText(f"Restored pending mark {record.filename}")

    def _update_marker_labels(self) -> None:
        self.lbl_start.setText(
            "not set" if self.start_frame is None else str(self.start_frame)
        )
        end_preview = self.player.frame_index if self.start_frame is not None else None
        self.lbl_end.setText("—" if end_preview is None else str(end_preview))
        if (
            self.start_frame is not None
            and end_preview is not None
            and end_preview > self.start_frame
            and self.player.reader is not None
        ):
            fps = self.player.reader.info.fps or 30.0
            n = end_preview - self.start_frame + 1
            self.lbl_duration.setText(f"{n} frames ({n / fps:.3f} s)")
        else:
            self.lbl_duration.setText("—")

    # ----------------------------------------------------------- exporting
    def export_all(self) -> None:
        if self.session is None:
            return
        if not self.session.pending:
            self.status.setText("Nothing to export.")
            return
        self._start_export(list(self.session.pending))

    def export_selected(self) -> None:
        records = self._selected_pending_records()
        if not records:
            QMessageBox.information(
                self, "Select clips",
                "Select one or more rows in the pending list first.",
            )
            return
        self._start_export(records)

    def _selected_pending_records(self) -> list[ClipRecord]:
        if self.session is None:
            return []
        by_index = {p.index: p for p in self.session.pending}
        out = []
        for item in self.pending_list.selectedItems():
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx in by_index:
                out.append(by_index[idx])
        return out

    def _start_export(self, records: list[ClipRecord]) -> None:
        if self._worker is not None or self.player.reader is None or not records:
            return
        fps = self.player.reader.info.fps or 30.0
        quality = self.quality_combo.currentData()
        jobs: list[tuple[int, ExportRequest]] = []
        for rec in records:
            req = ExportRequest(
                source=self.session.source,
                output=self.output_dir / rec.filename,
                start_frame=rec.start_frame,
                end_frame=rec.end_frame,
                fps=fps,
                quality=quality,
            )
            jobs.append((rec.index, req))

        self._set_export_running(True)
        self.export_bar.setValue(0)
        self.status.setText(f"Exporting {len(jobs)} clip(s) …")

        worker = BatchExportWorker(jobs, self)
        worker.progress.connect(self._on_batch_progress)
        worker.one_done.connect(self._on_one_exported)
        worker.finished_all.connect(self._on_batch_finished)
        worker.failed.connect(self._on_batch_failed)
        self._worker = worker
        worker.start()

    def _on_batch_progress(self, done: int, total: int, frac: float) -> None:
        overall = (done + frac) / total if total else 0.0
        self.export_bar.setValue(int(overall * 100))

    def _on_one_exported(self, index: int) -> None:
        if self.session is None:
            return
        rec = next((p for p in self.session.pending if p.index == index), None)
        if rec is not None:
            self.session.mark_exported(rec)  # persists pending + exported
        self._refresh_all()
        self._refresh_current_list_item()

    def _on_batch_finished(self) -> None:
        self._worker = None
        self._set_export_running(False)
        self.export_bar.setValue(100)
        self.status.setText("Export complete.")

    def _on_batch_failed(self, message: str) -> None:
        self._worker = None
        self._set_export_running(False)
        QMessageBox.critical(self, "Export failed", message)
        self.status.setText("Export failed (already-rendered clips were kept).")

    def _set_export_running(self, running: bool) -> None:
        for w in (
            self.btn_export_all,
            self.btn_export_selected,
            self.video_list,
            self.quality_combo,
        ):
            w.setEnabled(not running)
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        """Undo/redo availability depends on session state and export status."""
        running = self._worker is not None
        self.btn_undo_mark.setEnabled(
            not running and bool(self.session and self.session.can_undo)
        )
        self.btn_redo_mark.setEnabled(
            not running and bool(self.session and self.session.can_redo)
        )

    def _maybe_checkpoint(self) -> None:
        if not self.chk_autoexport.isChecked() or self._worker is not None:
            return
        if self.session and len(self.session.pending) >= self.spin_n.value():
            self.status.setText("Auto-export checkpoint …")
            self.export_all()

    # ------------------------------------------------------------ refresh
    def _refresh_all(self) -> None:
        self._refresh_next_target()
        self._refresh_pending_panel()
        self._refresh_exported_panel()
        self._update_marker_labels()
        self._update_action_buttons()

    def _refresh_next_target(self) -> None:
        if self.session is None:
            return
        t = self.session.next_target()
        self.lbl_target.setText(
            f"#{t.index}: {t.filename}\n({t.direction} · rep {t.repetition:02d})"
        )

    def _refresh_pending_panel(self) -> None:
        if self.session is None:
            return
        self.pending_list.clear()
        for c in self.session.pending:
            item = QListWidgetItem(
                f"#{c.index}  {c.filename}   [f{c.start_frame}–{c.end_frame}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, c.index)
            self.pending_list.addItem(item)

    def _refresh_exported_panel(self) -> None:
        if self.session is None:
            return
        counts = counts_per_direction(
            self.session.exported, self.session.spec.directions
        )
        self.lbl_counts.setText(
            "   ".join(f"{d}: {c}" for d, c in counts.items())
            + f"   ·   exported: {len(self.session.exported)}"
            + f"   ·   pending: {len(self.session.pending)}"
        )
        self.exported_list.clear()
        for c in self.session.exported:
            self.exported_list.addItem(
                f"{c.filename}   [f{c.start_frame}–{c.end_frame}]"
            )

    def _refresh_current_list_item(self) -> None:
        row = self.video_list.currentRow()
        if row < 0 or self.session is None:
            return
        item = self.video_list.item(row)
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        item.setText(self._format_list_label(path, self.session))

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        if self.player.reader is not None:
            self.player.reader.release()
        super().closeEvent(event)
