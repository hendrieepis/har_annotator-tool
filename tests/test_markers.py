"""Marker model: roles per direction, clamping, persistence."""

from har_annotator.core.markers import MIN_GAP, MarkerSet, marker_roles, start_stop_keys


def test_start_stop_per_direction():
    assert start_stop_keys("KKN") == ("x_left", "x_right")    # kiri -> kanan
    assert start_stop_keys("KNK") == ("x_right", "x_left")    # kanan -> kiri
    assert start_stop_keys("MDK") == ("y_top", "y_bottom")    # atas -> bawah
    assert start_stop_keys("MJH") == ("y_bottom", "y_top")    # bawah -> atas
    assert start_stop_keys("XXX") is None


def test_roles_only_for_used_axis():
    roles = marker_roles(("KKN", "KNK"))
    assert set(roles) == {"x_left", "x_right"}
    assert roles["x_left"] == [("KKN", "START"), ("KNK", "STOP")]
    assert roles["x_right"] == [("KKN", "STOP"), ("KNK", "START")]
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
    assert start_stop_keys("KKN", flip=True) == ("x_right", "x_left")
    assert start_stop_keys("KNK", flip=True) == ("x_left", "x_right")
    assert start_stop_keys("MDK", flip=True) == ("y_bottom", "y_top")
    # forward only + swapped labels: the left -> right walk is called KNK
    assert marker_roles(("KKN",), "forward", flip=True) == {
        "x_left": [("KNK", "START")], "x_right": [("KNK", "STOP")],
    }
    m = MarkerSet(flip=True)
    p = tmp_path / "m.json"
    m.save(p)
    assert MarkerSet.load(p).flip is True
    assert MarkerSet.from_dict({"x_left": 0.2}).flip is False   # old sidecars
