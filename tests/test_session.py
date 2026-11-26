"""Tests for pending/exported session state, persistence, and resume."""

from pathlib import Path

from har_annotator.core.session import (  # noqa: E402
    AnnotationSession,
    counts_per_direction,
)

SRC = Path("P001_BRJ_KKN_KNK_NORMAL.mp4")


def new_session(tmp_path) -> AnnotationSession:
    return AnnotationSession.load_or_create(SRC, tmp_path / "clips")


def test_add_mark_naming_and_sequence(tmp_path):
    s = new_session(tmp_path)
    r1 = s.add_mark(10, 20)
    r2 = s.add_mark(30, 40)
    r3 = s.add_mark(50, 60)
    assert [r.filename for r in (r1, r2, r3)] == [
        "P001_BRJ_KKN_NORMAL_01.mp4",
        "P001_BRJ_KNK_NORMAL_01.mp4",
        "P001_BRJ_KKN_NORMAL_02.mp4",
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
    assert resumed.pending[1].filename == "P001_BRJ_KNK_NORMAL_01.mp4"
    assert not resumed.exported


def test_undo_last_mark(tmp_path):
    s = new_session(tmp_path)
    s.add_mark(10, 20)
    s.add_mark(30, 40)
    removed = s.remove_last_mark()
    assert removed.filename == "P001_BRJ_KNK_NORMAL_01.mp4"
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
    assert s.exported[0].filename == "P001_BRJ_KKN_NORMAL_01.mp4"
    # fresh load: exported persisted to <stem>.json, pending still has the other
    resumed = new_session(tmp_path)
    assert len(resumed.exported) == 1
    assert len(resumed.pending) == 1
    assert resumed.pending[0].filename == "P001_BRJ_KNK_NORMAL_01.mp4"


def test_index_continuous_after_selected_export(tmp_path):
    # Export a non-last pending clip; new marks must not collide with it.
    s = new_session(tmp_path)
    s.add_mark(0, 5)      # idx 1
    r2 = s.add_mark(6, 10)  # idx 2
    s.add_mark(11, 15)    # idx 3
    s.mark_exported(r2)   # exported keeps idx 2
    nxt = s.next_target()
    assert nxt.index == 4
    assert nxt.filename == "P001_BRJ_KNK_NORMAL_02.mp4"


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
    assert counts == {"KKN": 2, "KNK": 2}


def test_add_mark_rejects_same_start_and_end(tmp_path):
    import pytest

    s = new_session(tmp_path)
    with pytest.raises(ValueError):
        s.add_mark(10, 10)
    with pytest.raises(ValueError):
        s.add_mark(20, 10)
    assert s.pending == []
