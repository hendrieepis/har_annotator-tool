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
    QDoubleSpinBox,
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
    QRadioButton,
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
from har_annotator.core.autoclip import Trajectory, find_passes
from har_annotator.core.markers import MarkerSet, marker_roles
from har_annotator.core.naming import FilenameSpec
from har_annotator.core.session import (
    AnnotationSession,
    ClipRecord,
    counts_per_direction,
)
from har_annotator.ui.auto_worker import TrajectoryWorker
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
        self.markers = MarkerSet()           # draggable start/stop lines
        self.auto_mode = False               # False = manual (Set Start/End)
        self._traj: Trajectory | None = None
        self._traj_worker: TrajectoryWorker | None = None
        self._play_after_analysis = False    # user pressed Play before analysis
        self._auto_active = False            # a live auto-clip run is in progress
        self._preview = False                # playing only to adjust the markers
        self._analysis_play = False          # analysis was started by Play
        self._auto_chain = False             # keep exporting until nothing is left
        self._auto_queue: list = []          # detected passes still ahead
        self._auto_stats = {"added": 0, "dup": 0, "order": 0}

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

        self.player.markersEdited.connect(self._on_markers_edited)
        self.player.play_guard = self._play_guard
        self.player.playbackStopped.connect(self._on_playback_stopped)

        # --- mode: manual (old way) / auto clip from the draggable markers
        mode_row = QHBoxLayout()
        self.rb_manual = QRadioButton("Manual (Set Start / Set End)")
        self.rb_auto = QRadioButton("Auto clip (from markers)")
        self.rb_manual.setChecked(True)
        self.rb_auto.toggled.connect(self._on_mode_toggled)
        self.chk_show_markers = QCheckBox("Show markers")
        self.chk_show_markers.setChecked(True)
        self.chk_show_markers.toggled.connect(self.player.set_markers_visible)
        self.chk_flip = QCheckBox("Reverse direction")
        self.chk_flip.setToolTip(
            "Swap START and STOP lines. Use when the walking direction in the "
            "picture is the mirror of the direction in the file name."
        )
        self.chk_flip.toggled.connect(self._on_flip_toggled)
        mode_row.addWidget(QLabel("Mode:"))
        mode_row.addWidget(self.rb_manual)
        mode_row.addWidget(self.rb_auto)
        mode_row.addStretch(1)
        mode_row.addWidget(self.chk_flip)
        mode_row.addWidget(self.chk_show_markers)

        # --- auto controls (hidden in manual mode)
        self.auto_box = QWidget()
        ab = QHBoxLayout(self.auto_box)
        ab.setContentsMargins(0, 0, 0, 0)
        self.btn_preview = QPushButton("👁 Preview (adjust markers)")
        self.btn_preview.setToolTip(
            "Play the video WITHOUT cutting clips so you can drag the markers "
            "into place. Then press Play & auto clip."
        )
        self.btn_preview.clicked.connect(self.toggle_preview)
        self.spin_pre = QDoubleSpinBox()
        self.spin_post = QDoubleSpinBox()
        for spin, tip in (
            (self.spin_pre, "Seconds kept BEFORE the START line (clip begins earlier)"),
            (self.spin_post, "Seconds kept AFTER the STOP line (clip ends later)"),
        ):
            spin.setRange(0.0, 30.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setSuffix(" s")
            spin.setToolTip(tip)
            spin.valueChanged.connect(self._on_roll_changed)
        self.lbl_auto = QLabel("Auto clip is idle.")
        self.lbl_auto.setWordWrap(True)
        self.btn_clear_pending = QPushButton("🗑 Clear pending")
        self.btn_clear_pending.setToolTip(
            "Remove all pending clips (Redo restores them one by one)"
        )
        self.btn_clear_pending.clicked.connect(self.clear_pending)
        self.auto_bar = QProgressBar()
        self.auto_bar.setRange(0, 100)
        self.auto_bar.setVisible(False)
        ab.addWidget(self.btn_preview, 2)
        ab.addWidget(QLabel("Pre-roll"))
        ab.addWidget(self.spin_pre)
        ab.addWidget(QLabel("Post-roll"))
        ab.addWidget(self.spin_post)
        ab.addWidget(self.lbl_auto, 3)
        ab.addWidget(self.auto_bar, 1)
        ab.addWidget(self.btn_clear_pending, 1)
        self.auto_box.setVisible(False)

        self.manual_box = QWidget()
        mark_row = QHBoxLayout(self.manual_box)
        mark_row.setContentsMargins(0, 0, 0, 0)
        self.btn_start = QPushButton("⟦ Set Start (I)")
        self.btn_start.clicked.connect(self.mark_start)
        self.btn_end = QPushButton("Set End (O) → add to pending ⟧")
        self.btn_end.clicked.connect(self.mark_end)
        mark_row.addWidget(self.btn_start)
        mark_row.addWidget(self.btn_end)
        # Step guide: always says which button to press next.
        self.lbl_step = QLabel()
        self.lbl_step.setWordWrap(True)
        self.lbl_step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.addWidget(self.player, 1)
        cl.addLayout(mode_row)
        cl.addWidget(self.lbl_step)
        cl.addWidget(self.manual_box)
        cl.addWidget(self.auto_box)
        self._update_mark_buttons()

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
        self.pending_list.setToolTip("Double-click a clip to jump to its start")
        self.pending_list.itemDoubleClicked.connect(self._seek_to_pending)
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
        self._load_markers()
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
        if self._auto_active and self.player.is_playing:
            self._auto_emit(index)

    def mark_start(self) -> None:
        if self.session is None or self.auto_mode:
            return
        self.start_frame = self.player.frame_index
        if self.end_frame is not None and self.end_frame < self.start_frame:
            self.end_frame = None
        self.player.set_markers(self.start_frame, self.end_frame)
        self._update_marker_labels()
        self._update_mark_buttons()
        self.status.setText(
            f"Start frame = {self.start_frame}. Now move to the end frame and "
            "press Set End (O)."
        )

    def mark_end(self) -> None:
        if self.session is None or self.auto_mode:
            return
        if self.start_frame is None:
            QMessageBox.information(
                self, "Set start first", "Set a start frame (I) before the end."
            )
            return
        end = self.player.frame_index
        if end == self.start_frame:  # start and end may not coincide
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
        self._update_mark_buttons()
        self.status.setText(
            f"Marked {record.filename} (pending). Next: press Set Start (I)."
        )
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
        if self._auto_chain:
            if self.session is not None and self.session.pending:
                self._start_export(list(self.session.pending))  # clips arrived meanwhile
            elif not self._auto_active:
                self._auto_chain = False
                self.status.setText("Auto clip: all clips exported.")
                self.lbl_auto.setText("Auto clip done: all clips exported.")

    def _on_batch_failed(self, message: str) -> None:
        self._worker = None
        self._auto_chain = False
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

    # Highlighted = the button the operator should press next.
    _ACTIVE_STYLE = (
        "QPushButton{background:#2e7d32;color:white;font-weight:bold;"
        "border:2px solid #1b5e20;border-radius:4px;padding:8px;}"
        "QPushButton:hover{background:#388e3c;}"
    )
    _IDLE_STYLE = "QPushButton{padding:8px;}"

    def _update_mark_buttons(self) -> None:
        """Two-step marking: Start (highlighted) -> End (highlighted).

        * no start yet : only **Set Start** is enabled + highlighted.
        * start is set : **Set End** becomes the highlighted, enabled button;
          Start stays available (un-highlighted) to correct the start frame.
        """
        if self.session is None:
            self.btn_start.setEnabled(False)
            self.btn_end.setEnabled(False)
            self.btn_start.setStyleSheet(self._IDLE_STYLE)
            self.btn_end.setStyleSheet(self._IDLE_STYLE)
            self.lbl_step.setText("Open a folder and pick a video to begin.")
            return
        if self.auto_mode:
            self.lbl_step.setText(
                "<b>Auto clip</b> — (1) drag the two marker lines to the walking "
                "boundaries (press <b>Preview</b> to play without cutting clips), "
                "(2) press <b>Play &amp; auto clip</b>. Each time the subject walks "
                "from a START line to its STOP line, a clip is cut and exported "
                "automatically, until the video ends."
            )
            return
        has_start = self.start_frame is not None
        self.btn_start.setEnabled(True)
        self.btn_end.setEnabled(has_start)
        self.btn_start.setStyleSheet(
            self._IDLE_STYLE if has_start else self._ACTIVE_STYLE
        )
        self.btn_end.setStyleSheet(
            self._ACTIVE_STYLE if has_start else self._IDLE_STYLE
        )
        self.btn_start.setText(
            "⟦ Re-set Start (I)" if has_start else "⟦ Set Start (I)"
        )
        if has_start:
            self.lbl_step.setText(
                f"<b>Step 2/2</b> — Start = frame {self.start_frame}. "
                "Move to the last good frame, then press <b>Set End (O)</b>."
            )
        else:
            self.lbl_step.setText(
                "<b>Step 1/2</b> — Move to the first frame where the whole body "
                "is visible, then press <b>Set Start (I)</b>."
            )

    def _update_action_buttons(self) -> None:
        """Undo/redo availability depends on session state and export status."""
        self._update_mark_buttons()
        running = self._worker is not None
        self.btn_undo_mark.setEnabled(
            not running and bool(self.session and self.session.can_undo)
        )
        self.btn_redo_mark.setEnabled(
            not running and bool(self.session and self.session.can_redo)
        )

    # ------------------------------------------------- markers & auto clip
    def _marker_labels(self) -> dict[str, str]:
        """Caption per line, e.g. 'KKN START | KNK STOP' (axes in use only)."""
        if self.session is None:
            return {}
        roles = marker_roles(self.session.spec.directions, self.markers.flip)
        return {
            key: " | ".join(f"{d} {r}" for d, r in items)
            for key, items in roles.items()
        }

    def _load_markers(self) -> None:
        assert self.session is not None
        path = self.session.markers_path()
        self.markers = MarkerSet.load(path) if path.exists() else MarkerSet()
        self.chk_flip.blockSignals(True)
        self.chk_flip.setChecked(self.markers.flip)
        self.chk_flip.blockSignals(False)
        for spin, val in (
            (self.spin_pre, self.markers.pre_roll),
            (self.spin_post, self.markers.post_roll),
        ):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        self._traj = None
        self.player.set_marker_overlay(self.markers, self._marker_labels())
        self.player.set_markers_visible(self.chk_show_markers.isChecked())
        if not self._marker_labels():
            self.status.setText(
                "Directions not recognised for markers "
                "(known: KKN, KNK, MDK, MJH) — use Manual mode."
            )

    def _on_markers_edited(self) -> None:
        if self.session is None:
            return
        self.markers.save(self.session.markers_path())
        self.status.setText("Markers saved for this video.")
        self._update_auto_hint()

    def _on_roll_changed(self, _value: float) -> None:
        if self.session is None or self._auto_active:
            return
        self.markers.pre_roll = self.spin_pre.value()
        self.markers.post_roll = self.spin_post.value()
        self.markers.save(self.session.markers_path())
        self._update_auto_hint()

    def _on_flip_toggled(self, on: bool) -> None:
        if self.session is None or self._auto_active:
            self.chk_flip.blockSignals(True)
            self.chk_flip.setChecked(self.markers.flip)
            self.chk_flip.blockSignals(False)
            return
        self.markers.flip = on
        self.markers.save(self.session.markers_path())
        self.player.set_marker_overlay(self.markers, self._marker_labels())
        self._update_auto_hint()
        self.status.setText(
            "Direction reversed: START and STOP lines swapped." if on
            else "Direction back to normal."
        )

    def _on_mode_toggled(self, auto: bool) -> None:
        if not auto and self._preview:
            self.player.stop()
        self.auto_mode = auto
        self.manual_box.setVisible(not auto)
        self.auto_box.setVisible(auto)
        self.player.set_play_text("▶ Play & auto clip" if auto else "▶ Play")
        self._update_mark_buttons()

    # -- live auto clip: Play drives detection + export --------------------
    def _play_guard(self) -> bool:
        """Called before every Play. In auto mode, make sure the motion analysis
        exists (run it first if not) and arm the run."""
        if not self.auto_mode or self.session is None or self._preview:
            return True
        if not self._marker_labels():
            QMessageBox.information(
                self, "Auto clip unavailable",
                "Auto clip needs directions KKN/KNK (left-right) or MDK/MJH "
                "(toward-away) in the file name. Use Manual mode.",
            )
            return False
        if self._traj_worker is not None:
            return False                      # analysis still running
        if self._traj is None:
            self._start_analysis()
            return False                      # playback starts when it is ready
        self._begin_auto_run()
        return True

    def _start_analysis(self, play_after: bool = True) -> None:
        """Run the motion analysis in the background. With ``play_after`` the UI
        waits for it and then starts the auto run; otherwise (preview) playback
        is untouched and only the live pass count is filled in afterwards."""
        self._analysis_play = play_after
        worker = TrajectoryWorker(
            self.session.source, self.session.trajectory_cache_path(), self
        )
        worker.progress.connect(self.auto_bar.setValue)
        worker.done.connect(self._on_traj_ready)
        worker.failed.connect(self._on_traj_failed)
        worker.finished.connect(self._on_traj_finished)
        self._traj_worker = worker
        self.auto_bar.setValue(0)
        self.auto_bar.setVisible(True)
        if play_after:
            self.player.btn_play.setEnabled(False)
            self.lbl_auto.setText("Analysing motion … (first time only, then cached)")
            self.status.setText("Analysing motion before playback …")
        else:
            self.lbl_auto.setText("Previewing … (analysing motion in background)")
        worker.start()

    def _on_traj_ready(self, traj: Trajectory) -> None:
        self._traj = traj
        self._play_after_analysis = self._analysis_play  # started by _on_traj_finished

    def _on_traj_failed(self, msg: str) -> None:
        self._play_after_analysis = False
        self.lbl_auto.setText(f"Auto clip failed: {msg}")
        self.status.setText(f"Auto clip failed: {msg}")

    def _on_traj_finished(self) -> None:
        if self._traj_worker is not None:
            self._traj_worker.deleteLater()
        self._traj_worker = None
        self.auto_bar.setVisible(False)
        self.player.btn_play.setEnabled(True)
        if self._play_after_analysis:
            self._play_after_analysis = False
            if self.auto_mode and self.session is not None:
                self.player.play()
        else:
            self._update_auto_hint()

    # -- preview: play without cutting, to adjust the markers ---------------
    def toggle_preview(self) -> None:
        if self.session is None or self._auto_active:
            return
        if self.player.is_playing:
            self.player.stop()
            return
        if not self._marker_labels():
            self._play_guard()                # shows the "unavailable" message
            return
        self._preview = True
        self.btn_preview.setText("⏸ Stop preview")
        self.lbl_auto.setText("Previewing — drag the markers; no clips are cut.")
        if self._traj is None and self._traj_worker is None:
            self._start_analysis(play_after=False)
        self.player.play()
        if not self.player.is_playing:        # play() was vetoed
            self._end_preview()

    def _end_preview(self) -> None:
        self._preview = False
        self.btn_preview.setText("👁 Preview (adjust markers)")
        self._update_auto_hint()

    def _update_auto_hint(self) -> None:
        """Idle caption: how many passes the current markers would produce."""
        if self._auto_active or self._preview or self._traj_worker is not None:
            return
        if self._traj is None or self.session is None:
            self.lbl_auto.setText(
                "Adjust the markers (Preview to play), then Play & auto clip."
            )
            return
        passes = find_passes(self._traj, self.markers, self.session.spec.directions)
        if not passes:
            self.lbl_auto.setText(
                "No pass between these markers — move the lines onto the walking path."
            )
            return
        counts = {}
        for ps in passes:
            counts[ps.direction] = counts.get(ps.direction, 0) + 1
        detail = " · ".join(f"{d} {n}" for d, n in counts.items())
        self.lbl_auto.setText(f"With these markers: {detail} pass(es) detected.")

    def _begin_auto_run(self) -> None:
        """Arm a run from the current frame with the *current* marker positions."""
        passes = find_passes(self._traj, self.markers, self.session.spec.directions)
        here = self.player.frame_index
        self._auto_queue = [p for p in passes if p.start_frame >= here]
        self._auto_active = True
        self._auto_chain = True
        self.player.set_markers_locked(True)
        self.btn_preview.setEnabled(False)
        self.chk_flip.setEnabled(False)
        self.spin_pre.setEnabled(False)
        self.spin_post.setEnabled(False)
        self.lbl_auto.setText("Running … clips are cut as the subject crosses.")
        self.status.setText(
            f"Auto clip running ({len(self._auto_queue)} pass(es) ahead). "
            "Pause to adjust the markers."
        )

    def _auto_emit(self, upto: int) -> None:
        """Create clips for every detected pass that has finished by *upto*."""
        if self.session is None:
            return
        added = False
        while self._auto_queue and self._auto_queue[0].end_frame <= upto:
            ps = self._auto_queue.pop(0)
            taken = [
                (c.start_frame, c.end_frame)
                for c in (*self.session.pending, *self.session.exported)
            ]
            if any(ps.start_frame <= e and s <= ps.end_frame for s, e in taken):
                self._auto_stats["dup"] += 1
                continue
            if ps.direction != self.session.next_target().direction:
                self._auto_stats["order"] += 1  # keep KKN,KNK,KKN… naming right
                continue
            rec = self.session.add_mark(ps.start_frame, ps.end_frame)
            self._auto_stats["added"] += 1
            added = True
            self.status.setText(f"Auto clip: {rec.filename} (f{rec.start_frame}–{rec.end_frame})")
        if added:
            self._refresh_all()
            self._refresh_current_list_item()
            self._auto_export_if_idle()

    def _auto_export_if_idle(self) -> None:
        if self._worker is None and self.session and self.session.pending:
            self._start_export(list(self.session.pending))

    def _on_playback_stopped(self, finished: bool) -> None:
        if self._preview:
            self._end_preview()
            return
        if not self._auto_active:
            return
        if finished and self.player.reader is not None:
            self._auto_emit(self.player.reader.info.frame_count)  # flush the tail
        self._auto_active = False
        self._auto_queue = []
        self.player.set_markers_locked(False)
        self.btn_preview.setEnabled(True)
        self.chk_flip.setEnabled(True)
        self.spin_pre.setEnabled(True)
        self.spin_post.setEnabled(True)
        st = self._auto_stats
        extra = []
        if st["order"]:
            extra.append(f"{st['order']} skipped: direction out of order")
        if st["dup"]:
            extra.append(f"{st['dup']} already marked")
        tail = f" ({'; '.join(extra)})" if extra else ""
        if finished:
            msg = f"Auto clip finished: {st['added']} clip(s) created{tail}."
            self._auto_stats = {"added": 0, "dup": 0, "order": 0}
        else:
            msg = (
                f"Paused: {st['added']} clip(s) so far{tail}. Adjust the markers "
                "if needed, then press Play to continue."
            )
        self.lbl_auto.setText(msg)
        self.status.setText(msg)
        if finished and self._worker is None:
            self._auto_chain = False
        self._auto_export_if_idle()

    def clear_pending(self) -> None:
        if self.session is None or not self.session.pending:
            return
        n = len(self.session.pending)
        if QMessageBox.question(
            self, "Clear pending",
            f"Remove all {n} pending clip(s)? (Redo can restore them.)",
        ) != QMessageBox.StandardButton.Yes:
            return
        while self.session.remove_last_mark() is not None:
            pass
        self._refresh_all()
        self._refresh_current_list_item()
        self.status.setText(f"Cleared {n} pending clip(s).")

    def _seek_to_pending(self, item: QListWidgetItem) -> None:
        if self.session is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        for c in self.session.pending:
            if c.index == idx:
                self.player.seek(c.start_frame)
                return

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
