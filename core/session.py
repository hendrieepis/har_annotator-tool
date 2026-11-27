"""Per-source annotation state with JSON persistence.

A session keeps two ordered lists for one source video:

* **pending** — clips the operator has *marked* (start/end chosen, name &
  numbering already computed) but **not yet rendered** to a physical file.
* **exported** — clips that have been rendered to disk by ffmpeg.

The pending list is auto-persisted to ``<stem>.pending.json`` on every change so
a crash mid-marking never loses progress. Exported clips live in the existing
``<stem>.json`` progress file. The running clip index (which drives direction +
repetition naming) is continuous across both lists.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .markers import canonical_direction
from .naming import FilenameSpec

STATE_DIRNAME = ".har_annotator"


@dataclass
class ClipRecord:
    index: int
    direction: str
    repetition: int
    start_frame: int
    end_frame: int
    filename: str
    # Set when this file is a copy of another clip that filled a deleted trial.
    duplicate_of: str | None = None


@dataclass
class DeleteResult:
    removed: list["ClipRecord"]
    filled: list["ClipRecord"]   # duplicates created in place of removed clips


def _rel_to(path: Path, base: Path) -> str:
    """POSIX path of ``path`` relative to ``base`` (portable across moves).

    Falls back to the bare file name when no relative path exists (e.g. a
    different drive on Windows). Sidecars are informational only — loading
    never reads these paths — so this is lossless for the app.
    """
    try:
        rel = os.path.relpath(path, base)
    except ValueError:
        rel = Path(path).name
    return Path(rel).as_posix()


def counts_per_direction(
    records: list[ClipRecord], directions: tuple[str, ...]
) -> dict[str, int]:
    out: dict[str, int] = {d: 0 for d in directions}
    for c in records:
        out[c.direction] = out.get(c.direction, 0) + 1
    return out


@dataclass
class AnnotationSession:
    source: Path
    output_dir: Path
    spec: FilenameSpec
    pending: list[ClipRecord] = field(default_factory=list)
    exported: list[ClipRecord] = field(default_factory=list)
    # In-memory undo/redo stack for marks (not persisted across restarts).
    _redo: list[ClipRecord] = field(default_factory=list, repr=False)

    # ----- derived -----------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self.pending)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def next_index(self) -> int:
        """Next running clip index, continuous across pending + exported.

        Uses ``max(index) + 1`` rather than a count so that removing a mark and
        re-marking reuses the freed index instead of colliding with an already
        exported clip.
        """
        indices = [c.index for c in self.pending] + [c.index for c in self.exported]
        return (max(indices) + 1) if indices else 1

    def next_target(self):
        return self.spec.target_for(self.next_index)

    def has_unexported(self) -> bool:
        return bool(self.pending)

    # ----- mutation ----------------------------------------------------
    def add_mark(
        self, start_frame: int, end_frame: int, direction: str | None = None
    ) -> ClipRecord:
        """Append a freshly-marked (not yet rendered) clip and persist.

        By default the name follows the alternating direction order of the
        source file name. With *direction* (auto clip) the clip is named for
        that direction and numbered within it.

        Raises ``ValueError`` unless ``end_frame > start_frame`` (a clip may
        not start and stop at the same time).
        """
        if end_frame <= start_frame:
            raise ValueError(
                f"end_frame ({end_frame}) must be after start_frame ({start_frame})"
            )
        if direction is None:
            target = self.next_target()
        else:
            used = {c.filename for c in (*self.pending, *self.exported)}
            repetition = 1 + sum(
                1 for c in (*self.pending, *self.exported) if c.direction == direction
            )
            target = self.spec.name_for(self.next_index, direction, repetition)
            while target.filename in used:  # a deleted clip left a gap: skip taken names
                repetition += 1
                target = self.spec.name_for(self.next_index, direction, repetition)
        record = ClipRecord(
            index=target.index,
            direction=target.direction,
            repetition=target.repetition,
            start_frame=start_frame,
            end_frame=end_frame,
            filename=target.filename,
        )
        self.pending.append(record)
        self._redo.clear()  # a fresh mark invalidates the redo history
        self.save_pending()
        return record

    def remove_last_mark(self) -> ClipRecord | None:
        """Undo: drop the most recently marked pending clip (cheap; no file)."""
        if not self.pending:
            return None
        record = self.pending.pop()
        self._redo.append(record)
        self.save_pending()
        return record

    def redo_last_mark(self) -> ClipRecord | None:
        """Redo: restore the most recently undone mark, exactly as it was."""
        if not self._redo:
            return None
        record = self._redo.pop()
        self.pending.append(record)
        self.save_pending()
        return record

    def mark_exported(self, record: ClipRecord) -> None:
        """Move a clip from pending to exported (after ffmpeg succeeds)."""
        self.pending = [p for p in self.pending if p.index != record.index]
        if all(e.index != record.index for e in self.exported):
            self.exported.append(record)
        self.exported.sort(key=lambda c: c.index)
        self.save_pending()
        self.save_exported()

    def delete_exported(
        self, records: list[ClipRecord], fill_gaps: bool = True
    ) -> DeleteResult:
        """Delete exported clips: remove the files and forget them in the state.

        A file that is already gone is not an error (the record is still
        dropped). With *fill_gaps*, a deleted trial that is followed by a later
        trial of the same direction is replaced by a **copy of the previous
        trial** (the next one when it was trial 01), so the numbering stays
        complete (01..N). The source video is never touched.
        """
        gone = {r.index for r in records}
        removed = [e for e in self.exported if e.index in gone]
        for rec in removed:
            try:
                (self.output_dir / rec.filename).unlink(missing_ok=True)
            except OSError as exc:
                raise OSError(f"Cannot delete {rec.filename}: {exc}") from exc
        self.exported = [e for e in self.exported if e.index not in gone]
        filled: list[ClipRecord] = []
        if fill_gaps:
            for rec in sorted(removed, key=lambda r: (r.direction, r.repetition)):
                dup = self._fill_gap(rec)
                if dup is not None:
                    filled.append(dup)
        self.save_exported()
        return DeleteResult(removed=removed, filled=filled)

    def _fill_gap(self, rec: ClipRecord) -> ClipRecord | None:
        if rec.duplicate_of:          # deleting a duplicate again really removes it
            return None
        same = [e for e in self.exported if e.direction == rec.direction]
        if not any(e.repetition > rec.repetition for e in same):
            return None               # last trial of its direction: nothing to fill
        lower = [e for e in same if e.repetition < rec.repetition]
        higher = [e for e in same if e.repetition > rec.repetition]
        src = max(lower, key=lambda e: e.repetition) if lower else min(
            higher, key=lambda e: e.repetition
        )
        src_file = self.output_dir / src.filename
        if not src_file.exists():
            return None
        shutil.copy2(src_file, self.output_dir / rec.filename)
        dup = ClipRecord(
            index=rec.index,
            direction=rec.direction,
            repetition=rec.repetition,
            start_frame=src.start_frame,
            end_frame=src.end_frame,
            filename=rec.filename,
            duplicate_of=src.filename,
        )
        self.exported.append(dup)
        self.exported.sort(key=lambda c: c.index)
        return dup

    # ----- persistence -------------------------------------------------
    def _state_dir(self) -> Path:
        return self.output_dir / STATE_DIRNAME

    def markers_path(self) -> Path:
        """Sidecar with the draggable start/stop marker positions of this video."""
        return self._state_dir() / f"{self.source.stem}.markers.json"

    def trajectory_cache_path(self) -> Path:
        """Cache of the motion analysis used by auto clip."""
        return self._state_dir() / f"{self.source.stem}.traj.npz"

    def _exported_path(self) -> Path:
        return self._state_dir() / f"{self.source.stem}.json"

    def _pending_path(self) -> Path:
        return self._state_dir() / f"{self.source.stem}.pending.json"

    def save_exported(self) -> None:
        path = self._exported_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "source": _rel_to(self.source, self.output_dir),
            "output_dir": ".",
            "directions": list(self.spec.directions),
            "prefix": self.spec.prefix,
            "suffix": self.spec.suffix,
            "extension": self.spec.extension,
            "clips": [asdict(c) for c in self.exported],
        }
        path.write_text(json.dumps(data, indent=2))

    def save_pending(self) -> None:
        path = self._pending_path()
        if not self.pending:
            # keep the state folder tidy: no stray empty pending file
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "source": _rel_to(self.source, self.output_dir),
            "pending": [asdict(c) for c in self.pending],
        }
        path.write_text(json.dumps(data, indent=2))

    def save(self) -> None:
        self.save_exported()
        self.save_pending()

    @staticmethod
    def _load_records(path: Path, key: str) -> list[ClipRecord]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            records = [ClipRecord(**c) for c in data.get(key, [])]
            for r in records:  # old sidecars used KKN/KNK
                r.direction = canonical_direction(r.direction)
            return records
        except (json.JSONDecodeError, TypeError, KeyError):
            return []  # corrupt sidecar -> ignore, don't crash the UI

    @classmethod
    def load_or_create(
        cls, source: Path, output_dir: Path, spec: FilenameSpec | None = None
    ) -> "AnnotationSession":
        source = Path(source)
        output_dir = Path(output_dir)
        spec = spec or FilenameSpec.parse(source)
        session = cls(source=source, output_dir=output_dir, spec=spec)
        session.exported = cls._load_records(session._exported_path(), "clips")
        session.pending = cls._load_records(session._pending_path(), "pending")
        return session
