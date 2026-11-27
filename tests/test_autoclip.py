"""Auto clip: pass detection on trajectories and on a synthetic video."""

import numpy as np
import pytest

from har_annotator.core.autoclip import Trajectory, compute_trajectory, find_passes
from har_annotator.core.markers import MarkerSet


def _traj(x, y=None):
    x = np.asarray(x, float)
    return Trajectory(30.0, x, np.asarray(y if y is not None else x * 0, float))


def test_full_passes_in_both_directions_alternate():
    x = np.concatenate([
        np.full(5, np.nan),
        np.linspace(0.05, 0.95, 60),      # KKN
        np.linspace(0.95, 0.05, 60),      # KNK
    ])
    passes = find_passes(_traj(x), MarkerSet(), ("KKN", "KNK"))
    assert [p.direction for p in passes] == ["KKN", "KNK"]
    assert all(p.end_frame > p.start_frame for p in passes)
    # KKN starts at the left line (0.25) and stops at the right line (0.75)
    assert abs(x[passes[0].start_frame] - 0.25) < 0.03
    assert abs(x[passes[0].end_frame] - 0.75) < 0.03
    assert abs(x[passes[1].start_frame] - 0.75) < 0.03   # KNK starts at right


def test_partial_walk_is_not_a_pass():
    x = np.concatenate([np.linspace(0.05, 0.6, 30), np.linspace(0.6, 0.05, 30)])
    assert find_passes(_traj(x), MarkerSet(), ("KKN", "KNK")) == []


def test_moving_markers_changes_result():
    x = np.concatenate([np.linspace(0.05, 0.6, 30), np.linspace(0.6, 0.05, 30)])
    m = MarkerSet(x_left=0.2, x_right=0.5)         # shorter span now fits
    assert [p.direction for p in find_passes(_traj(x), m, ("KKN", "KNK"))] == [
        "KKN", "KNK"
    ]


def test_depth_axis_uses_y():
    y = np.concatenate([np.linspace(0.05, 0.95, 60), np.linspace(0.95, 0.05, 60)])
    passes = find_passes(_traj(np.full(120, 0.5), y), MarkerSet(), ("MDK", "MJH"))
    assert [p.direction for p in passes] == ["MDK", "MJH"]


def test_lost_subject_cancels_open_pass():
    x = np.linspace(0.05, 0.95, 80)
    x[40:60] = np.nan                               # gone for too long mid-pass
    assert find_passes(_traj(x), MarkerSet(), ("KKN", "KNK")) == []


def _write_video(path, frames_x, w=320, h=180, fps=30):
    av = pytest.importorskip("av")
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=fps)
        s.width, s.height, s.pix_fmt = w, h, "yuv420p"
        for fx in frames_x:
            img = np.zeros((h, w, 3), np.uint8)
            cx = int(fx * w)
            img[40:150, max(cx - 12, 0): cx + 12] = 255   # the "walker"
            for pkt in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)


def test_trajectory_from_synthetic_video(tmp_path):
    xs = np.concatenate([np.linspace(0.05, 0.95, 50), np.linspace(0.95, 0.05, 50)])
    vid = tmp_path / "P001_BRJ_KKN_KNK_NORMAL.mp4"
    _write_video(vid, xs)
    traj = compute_trajectory(vid)
    assert len(traj.x) >= 95
    ok = ~np.isnan(traj.x[:100])
    assert ok.mean() > 0.9
    assert np.nanmax(np.abs(traj.x[:100][ok] - xs[ok])) < 0.08
    passes = find_passes(traj, MarkerSet(), ("KKN", "KNK"))
    assert [p.direction for p in passes] == ["KKN", "KNK"]
    # cache roundtrip
    cache = tmp_path / "t.npz"
    traj.save(cache, vid)
    again = Trajectory.load(cache, vid)
    assert again is not None and np.allclose(again.x, traj.x, equal_nan=True)


def test_flip_picks_the_opposite_walking_sense():
    x = np.concatenate([np.linspace(0.05, 0.95, 60), np.linspace(0.95, 0.05, 60)])
    t = _traj(x)
    normal = find_passes(t, MarkerSet(), ("KKN",))
    flipped = find_passes(t, MarkerSet(flip=True), ("KKN",))
    assert len(normal) == len(flipped) == 1
    assert normal[0].start_frame < 60 <= flipped[0].start_frame   # 1st vs 2nd leg


def test_pre_and_post_roll_extend_without_overlapping_neighbours():
    x = np.concatenate([
        np.full(5, np.nan),
        np.linspace(0.05, 0.95, 60),      # KKN
        np.linspace(0.95, 0.05, 60),      # KNK right after
    ])
    t = _traj(x)
    base = find_passes(t, MarkerSet(), ("KKN", "KNK"))
    rolled = find_passes(t, MarkerSet(pre_roll=0.5, post_roll=0.5), ("KKN", "KNK"))
    assert rolled[0].start_frame == base[0].start_frame - 15      # 0.5 s @ 30 fps
    assert rolled[0].end_frame > base[0].end_frame
    assert rolled[0].end_frame < rolled[1].start_frame           # no overlap
    assert rolled[1].end_frame <= len(x) - 1
    # no roll configured -> untouched
    assert find_passes(t, MarkerSet(), ("KKN", "KNK")) == base


def test_roll_is_clamped_at_video_start_and_persists(tmp_path):
    x = np.linspace(0.05, 0.95, 40)
    p = find_passes(_traj(x), MarkerSet(pre_roll=30.0), ("KKN",))[0]
    assert p.start_frame == 0
    m = MarkerSet(pre_roll=1.25, post_roll=0.4)
    f = tmp_path / "m.json"
    m.save(f)
    again = MarkerSet.load(f)
    assert (again.pre_roll, again.post_roll) == (1.25, 0.4)
