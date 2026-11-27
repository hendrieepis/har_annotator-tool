"""Marker model: roles per direction, clamping, persistence."""

from har_annotator.core.markers import MIN_GAP, MarkerSet, marker_roles, start_stop_keys


def test_start_stop_per_direction():
    assert start_stop_keys("KRKN") == ("x_left", "x_right")    # kiri -> kanan
    assert start_stop_keys("KNKR") == ("x_right", "x_left")    # kanan -> kiri
    assert start_stop_keys("MDK") == ("y_top", "y_bottom")    # atas -> bawah
    assert start_stop_keys("MJH") == ("y_bottom", "y_top")    # bawah -> atas
    assert start_stop_keys("XXX") is None


def test_roles_only_for_used_axis():
    roles = marker_roles(("KRKN", "KNKR"))
    assert set(roles) == {"x_left", "x_right"}
    assert roles["x_left"] == [("KRKN", "START"), ("KNKR", "STOP")]
    assert roles["x_right"] == [("KRKN", "STOP"), ("KNKR", "START")]
    assert set(marker_roles(("MDK", "MJH"))) == {"y_top", "y_bottom"}
    assert marker_roles(("AAA", "BBB")) == {}


def test_move_clamps_and_keeps_gap():
    m = MarkerSet()
    m.move("x_left", -5)
    assert m.x_left == 0.0
    m.move("x_left", 0.99)                       # cannot cross the right line
    assert m.x_left == m.x_right - MIN_GAP
    m.move("x_right", 0.0)
    assert m.x_right == m.x_left + MIN_GAP
    m.move("y_bottom", 7)
    assert m.y_bottom == 1.0


def test_save_load_roundtrip_and_repair(tmp_path):
    m = MarkerSet(x_left=0.1, x_right=0.9)
    p = tmp_path / "sub" / "m.json"
    m.save(p)
    assert MarkerSet.load(p) == m
    p.write_text('{"x_left": 0.8, "x_right": 0.2}')   # inverted -> defaults
    fixed = MarkerSet.load(p)
    assert fixed.x_left < fixed.x_right
    p.write_text("not json")
    assert MarkerSet.load(p) == MarkerSet()


def test_flip_swaps_start_and_stop_and_persists(tmp_path):
    assert start_stop_keys("KRKN", flip=True) == ("x_right", "x_left")
    assert start_stop_keys("KNKR", flip=True) == ("x_left", "x_right")
    assert start_stop_keys("MDK", flip=True) == ("y_bottom", "y_top")
    # forward only + swapped labels: the left -> right walk is called KNKR
    assert marker_roles(("KRKN",), "forward", flip=True) == {
        "x_left": [("KNKR", "START")], "x_right": [("KNKR", "STOP")],
    }
    m = MarkerSet(flip=True)
    p = tmp_path / "m.json"
    m.save(p)
    assert MarkerSet.load(p).flip is True
    assert MarkerSet.from_dict({"x_left": 0.2}).flip is False   # old sidecars


def test_global_markers_only_share_positions(tmp_path, monkeypatch):
    from har_annotator.core.markers import load_global_markers, save_global_markers

    monkeypatch.setenv("HAR_ANNOTATOR_CONFIG", str(tmp_path / "cfg"))
    assert load_global_markers() == MarkerSet()          # nothing saved yet
    m = MarkerSet(x_left=0.1, x_right=0.9, y_top=0.5, y_bottom=0.8,
                  flip=True, mode="forward", pad_lo=2.0, pad_hi=3.0)
    save_global_markers(m)
    g = load_global_markers()
    assert (g.x_left, g.x_right, g.y_top, g.y_bottom) == (0.1, 0.9, 0.5, 0.8)
    assert g.flip is False and g.mode == "both" and g.pad_lo == 0.0
    (tmp_path / "cfg" / "markers.json").write_text("not json")
    assert load_global_markers() == MarkerSet()          # corrupt -> defaults
