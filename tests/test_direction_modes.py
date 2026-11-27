"""Direction modes: forward / reverse / both (default), and direction-based naming."""

import numpy as np

from har_annotator.core.autoclip import Trajectory, find_passes
from har_annotator.core.markers import (
    MODES,
    MarkerSet,
    active_directions,
    marker_roles,
)
from har_annotator.core.naming import FilenameSpec
from har_annotator.core.session import AnnotationSession


def _traj():
    # right, left, right, left  (x sweeps the whole frame each time)
    x = np.concatenate([
        np.linspace(0.05, 0.95, 60), np.linspace(0.95, 0.05, 60),
        np.linspace(0.05, 0.95, 60), np.linspace(0.95, 0.05, 60),
    ])
    return Trajectory(30.0, x, x * 0)


def test_default_mode_is_both():
    assert MarkerSet().mode == "both"
    assert MarkerSet.from_dict({}).mode == "both"
    assert MarkerSet.from_dict({"mode": "nonsense"}).mode == "both"
    assert set(MODES) == {"forward", "reverse", "both"}


def test_single_code_filename_gets_both_directions_by_default():
    # a file called ..._KRKN_... still contains the way back
    passes = find_passes(_traj(), MarkerSet(), ("KRKN",))
    assert [p.direction for p in passes] == ["KRKN", "KNKR", "KRKN", "KNKR"]


def test_forward_and_reverse_pick_one_sense_each():
    fwd = find_passes(_traj(), MarkerSet(mode="forward"), ("KRKN",))
    rev = find_passes(_traj(), MarkerSet(mode="reverse"), ("KRKN",))
    assert [p.direction for p in fwd] == ["KRKN", "KRKN"]
    assert [p.direction for p in rev] == ["KNKR", "KNKR"]
    assert fwd[0].start_frame < rev[0].start_frame


def test_depth_axis_both_modes():
    y = np.concatenate([np.linspace(0.3, 0.98, 60), np.linspace(0.98, 0.3, 60)])
    t = Trajectory(30.0, y * 0, y)
    m = MarkerSet(y_top=0.4, y_bottom=0.9)
    assert [p.direction for p in find_passes(t, m, ("MDK",))] == ["MDK", "MJH"]
    m.mode = "reverse"
    assert [p.direction for p in find_passes(t, m, ("MDK",))] == ["MJH"]


def test_swap_labels_for_mirrored_recordings():
    both = active_directions(("KRKN",), "both", flip=True)
    assert [(c, s) for c, _, s in both] == [("KNKR", 1), ("KRKN", -1)]
    # the file-name code does not matter for the axis pair, only which axis
    assert active_directions(("KNKR", "KRKN"), "both") == active_directions(("KRKN",), "both")
    assert active_directions(("AAA",), "both") == []        # unknown -> unavailable
    assert marker_roles(("AAA",)) == {}


def test_mode_persists(tmp_path):
    f = tmp_path / "m.json"
    MarkerSet(mode="reverse", flip=True).save(f)
    m = MarkerSet.load(f)
    assert (m.mode, m.flip) == ("reverse", True)


def test_clips_are_named_by_walked_direction_with_separate_counters(tmp_path):
    spec = FilenameSpec.parse("P001_BRJ_KRKN_CEPAT.mp4")
    s = AnnotationSession.load_or_create(tmp_path / "P001_BRJ_KRKN_CEPAT.mp4", tmp_path, spec)
    names = [
        s.add_mark(10, 20, direction="KRKN").filename,
        s.add_mark(30, 40, direction="KNKR").filename,
        s.add_mark(50, 60, direction="KRKN").filename,
        s.add_mark(70, 80, direction="KNKR").filename,
    ]
    assert names == [
        "P001_BRJ_KRKN_CEPAT_01.mp4", "P001_BRJ_KNKR_CEPAT_01.mp4",
        "P001_BRJ_KRKN_CEPAT_02.mp4", "P001_BRJ_KNKR_CEPAT_02.mp4",
    ]
    assert [c.index for c in s.pending] == [1, 2, 3, 4]
    # undo frees the last number of that direction; manual naming still works
    s.remove_last_mark()
    assert s.add_mark(70, 80, direction="KNKR").filename == "P001_BRJ_KNKR_CEPAT_02.mp4"
