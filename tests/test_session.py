"""Tests for pending/exported session state, persistence, and resume."""

from pathlib import Path

from har_annotator.core.session import (  # noqa: E402
    AnnotationSession,
    counts_per_direction,
)

SRC = Path("P001_BRJ_KRKN_KNKR_NORMAL.mp4")


def new_session(tmp_path) -> AnnotationSession:
    return AnnotationSession.load_or_create(SRC, tmp_path / "clips")


def test_add_mark_naming_and_sequence(tmp_path):
    s = new_session(tmp_path)
    r1 = s.add_mark(10, 20)
    r2 = s.add_mark(30, 40)
    r3 = s.add_mark(50, 60)
    assert [r.filename for r in (r1, r2, r3)] == [
        "P001_BRJ_KRKN_NORMAL_01.mp4",
        "P001_BRJ_KNKR_NORMAL_01.mp4",
        "P001_BRJ_KRKN_NORMAL_02.mp4",
    ]
    assert len(s.pending) == 3 and not s.exported


def test_pending_autopersist_and_resume(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(10, 20)
    s.add_mark(30, 40)
    # a brand new session object for the same source must see the pending marks
    resumed = new_session(tmp_path)
    assert len(resumed.pending) == 2
    assert resumed.pending[0].start_frame == 10
    assert resumed.pending[1].filename == "P001_BRJ_KNKR_NORMAL_01.mp4"
    assert not resumed.exported


def test_undo_last_mark(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(10, 20)
    s.add_mark(30, 40)
    removed = s.remove_last_mark()
    assert removed.filename == "P001_BRJ_KNKR_NORMAL_01.mp4"
    assert len(s.pending) == 1
    # persisted: a fresh load sees only one pending
    assert len(new_session(tmp_path).pending) == 1
    # removing the last one deletes the pending sidecar entirely
    s.remove_last_mark()
    assert s.remove_last_mark() is None
    assert not s._pending_path().exists()
    assert len(new_session(tmp_path).pending) == 0


def test_mark_exported_moves_and_persists(tmp_path):
    s = new_session(tmp_path)
    r1 = s.add_mark(10, 20)
    s.add_mark(30, 40)
    s.mark_exported(r1)
    assert len(s.pending) == 1 and len(s.exported) == 1
    assert s.exported[0].filename == "P001_BRJ_KRKN_NORMAL_01.mp4"
    # fresh load: exported persisted to <stem>.json, pending still has the other
    resumed = new_session(tmp_path)
    assert len(resumed.exported) == 1
    assert len(resumed.pending) == 1
    assert resumed.pending[0].filename == "P001_BRJ_KNKR_NORMAL_01.mp4"


def test_index_continuous_after_selected_export(tmp_path):
    # Export a non-last pending clip; new marks must not collide with it.
    s = new_session(tmp_path)
    s.add_mark(0, 5)      # idx 1
    r2 = s.add_mark(6, 10)  # idx 2
    s.add_mark(11, 15)    # idx 3
    s.mark_exported(r2)   # exported keeps idx 2
    nxt = s.next_target()
    assert nxt.index == 4
    assert nxt.filename == "P001_BRJ_KNKR_NORMAL_02.mp4"


def test_redo_restores_undone_mark(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(10, 20)
    r2 = s.add_mark(30, 40)
    assert not s.can_redo
    s.remove_last_mark()
    assert s.can_redo and len(s.pending) == 1
    restored = s.redo_last_mark()
    assert restored.filename == r2.filename
    assert len(s.pending) == 2 and not s.can_redo
    # redo is persisted to the pending sidecar
    assert len(new_session(tmp_path).pending) == 2


def test_new_mark_clears_redo(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(10, 20)
    s.add_mark(30, 40)
    s.remove_last_mark()
    assert s.can_redo
    s.add_mark(50, 60)        # a fresh mark invalidates redo history
    assert not s.can_redo
    assert s.redo_last_mark() is None


def test_redo_after_export_keeps_indices_distinct(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(0, 5)      # idx 1
    s.add_mark(6, 10)     # idx 2
    undone = s.remove_last_mark()  # idx 2 -> redo
    # export the remaining pending clip, then redo the undone one
    s.mark_exported(s.pending[0])  # idx 1 exported
    restored = s.redo_last_mark()
    assert restored.index == undone.index == 2
    assert [c.index for c in s.exported] == [1]
    assert [c.index for c in s.pending] == [2]


def test_counts_per_direction(tmp_path):
    s = new_session(tmp_path)
    for i in range(4):
        s.add_mark(i * 10, i * 10 + 5)
    counts = counts_per_direction(s.pending, s.spec.directions)
    assert counts == {"KRKN": 2, "KNKR": 2}


def test_add_mark_rejects_same_start_and_end(tmp_path):
    import pytest

    s = new_session(tmp_path)
    with pytest.raises(ValueError):
        s.add_mark(10, 10)
    with pytest.raises(ValueError):
        s.add_mark(20, 10)
    assert s.pending == []


def test_delete_exported_removes_file_and_state(tmp_path):
    from har_annotator.core.naming import FilenameSpec
    from har_annotator.core.session import AnnotationSession

    src = tmp_path / "P001_BRJ_KRKN_KNKR_CEPAT.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "clips"
    out.mkdir()
    s = AnnotationSession.load_or_create(src, out, FilenameSpec.parse(src))
    recs = []
    for i in range(3):
        r = s.add_mark(i * 10, i * 10 + 5)
        (out / r.filename).write_bytes(b"clip")
        s.mark_exported(r)
        recs.append(r)

    removed = s.delete_exported([recs[1], recs[1]], fill_gaps=False).removed
    assert [r.index for r in removed] == [recs[1].index]
    assert not (out / recs[1].filename).exists()
    assert (out / recs[0].filename).exists() and (out / recs[2].filename).exists()
    reloaded = AnnotationSession.load_or_create(src, out, FilenameSpec.parse(src))
    assert [e.index for e in reloaded.exported] == [recs[0].index, recs[2].index]
    # already-missing file is fine
    (out / recs[0].filename).unlink()
    assert len(s.delete_exported([recs[0]], fill_gaps=False).removed) == 1


def test_auto_names_skip_taken_after_delete(tmp_path):
    from har_annotator.core.naming import FilenameSpec
    from har_annotator.core.session import AnnotationSession

    src = tmp_path / "P001_BRJ_KRKN_KNKR_CEPAT.mp4"
    src.write_bytes(b"x")
    s = AnnotationSession.load_or_create(src, tmp_path, FilenameSpec.parse(src))
    recs = []
    for i in range(3):
        r = s.add_mark(i * 10, i * 10 + 5, direction="KRKN")
        s.mark_exported(r)
        recs.append(r)
    s.delete_exported([recs[0]], fill_gaps=False)  # leaves _02 and _03
    new = s.add_mark(100, 110, direction="KRKN")
    taken = {e.filename for e in s.exported}
    assert new.filename not in taken


def test_delete_fills_gap_with_previous_trial(tmp_path):
    from har_annotator.core.naming import FilenameSpec
    from har_annotator.core.session import AnnotationSession

    src = tmp_path / "P001_BRJ_KRKN_KNKR_CEPAT.mp4"
    src.write_bytes(b"x")
    s = AnnotationSession.load_or_create(src, tmp_path, FilenameSpec.parse(src))
    recs = []
    for i in range(4):
        r = s.add_mark(i * 10, i * 10 + 5, direction="KRKN")
        (tmp_path / r.filename).write_bytes(f"clip{i}".encode())
        s.mark_exported(r)
        recs.append(r)

    res = s.delete_exported([recs[1], recs[2]])      # trials 02 and 03
    assert [d.repetition for d in res.filled] == [2, 3]
    assert (tmp_path / recs[1].filename).read_bytes() == b"clip0"
    assert (tmp_path / recs[2].filename).read_bytes() == b"clip0"   # chained copy
    assert all(d.duplicate_of for d in res.filled)
    assert [e.repetition for e in s.exported] == [1, 2, 3, 4]
    again = AnnotationSession.load_or_create(src, tmp_path, FilenameSpec.parse(src))
    assert [e.duplicate_of for e in again.exported][1] == recs[0].filename

    # deleting a duplicate, or the last trial, is a real delete
    res = s.delete_exported([s.exported[1]])
    assert res.filled == [] and len(s.exported) == 3
    res = s.delete_exported([s.exported[-1]])
    assert res.filled == [] and not (tmp_path / recs[3].filename).exists()


def test_delete_first_trial_copies_next(tmp_path):
    from har_annotator.core.naming import FilenameSpec
    from har_annotator.core.session import AnnotationSession

    src = tmp_path / "P001_BRJ_KRKN_KNKR_CEPAT.mp4"
    src.write_bytes(b"x")
    s = AnnotationSession.load_or_create(src, tmp_path, FilenameSpec.parse(src))
    recs = []
    for i in range(2):
        r = s.add_mark(i * 10, i * 10 + 5, direction="KRKN")
        (tmp_path / r.filename).write_bytes(f"clip{i}".encode())
        s.mark_exported(r)
        recs.append(r)
    res = s.delete_exported([recs[0]])
    assert (tmp_path / recs[0].filename).read_bytes() == b"clip1"
    assert res.filled[0].duplicate_of == recs[1].filename
