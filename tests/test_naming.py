"""Tests for the output-naming logic — the core correctness guarantee."""

from har_annotator.core.naming import FilenameSpec  # noqa: E402


def test_parse_basic():
    spec = FilenameSpec.parse("P001_BRJ_KKN_KNK_NORMAL.mp4")
    assert spec.prefix == ["P001", "BRJ"]
    assert spec.directions == ("KKN", "KNK")
    assert spec.suffix == ["NORMAL"]
    assert spec.extension == ".mp4"


def test_alternating_sequence_kkn_knk():
    spec = FilenameSpec.parse("P001_BRJ_KKN_KNK_NORMAL.mp4")
    names = [t.filename for t in spec.preview(4)]
    assert names == [
        "P001_BRJ_KKN_NORMAL_01.mp4",
        "P001_BRJ_KNK_NORMAL_01.mp4",
        "P001_BRJ_KKN_NORMAL_02.mp4",
        "P001_BRJ_KNK_NORMAL_02.mp4",
    ]


def test_order_follows_source_name():
    # directions swapped in the source -> output order swaps too
    spec = FilenameSpec.parse("P001_BRJ_KNK_KKN_NORMAL.mp4")
    first_two = [t.filename for t in spec.preview(2)]
    assert first_two == [
        "P001_BRJ_KNK_NORMAL_01.mp4",
        "P001_BRJ_KKN_NORMAL_01.mp4",
    ]


def test_mdk_mjh_to_ten_reps():
    spec = FilenameSpec.parse("P001_BRJ_MDK_MJH_NORMAL.mp4")
    targets = spec.preview(20)
    assert targets[-2].filename == "P001_BRJ_MDK_NORMAL_10.mp4"
    assert targets[-1].filename == "P001_BRJ_MJH_NORMAL_10.mp4"
    assert targets[18].direction == "MDK" and targets[18].repetition == 10


def test_target_fields():
    spec = FilenameSpec.parse("P002_BRJ_KKN_KNK_CEPAT.mp4")
    t = spec.target_for(5)  # 5th clip -> dir1, rep 3
    assert t.direction == "KKN"
    assert t.repetition == 3
    assert t.filename == "P002_BRJ_KKN_CEPAT_03.mp4"


def test_bad_name_raises():
    import pytest

    with pytest.raises(ValueError):
        FilenameSpec.parse("too_short.mp4")


def test_one_code_file_alternates_with_the_reverse_direction():
    spec = FilenameSpec.parse("P001_BRJ_KKN_CEPAT.mp4")
    assert spec.directions == ("KKN", "KNK")
    assert spec.prefix == ["P001", "BRJ"]
    assert spec.suffix == ["CEPAT"]
    assert [spec.target_for(i).filename for i in (1, 2, 3, 4, 20)] == [
        "P001_BRJ_KKN_CEPAT_01.mp4",
        "P001_BRJ_KNK_CEPAT_01.mp4",
        "P001_BRJ_KKN_CEPAT_02.mp4",
        "P001_BRJ_KNK_CEPAT_02.mp4",
        "P001_BRJ_KNK_CEPAT_10.mp4",
    ]


def test_depth_file_alternates_mdk_mjh_like_the_reported_bug():
    # P002_BRJ_MDK_CEPAT.mp4: the 2nd clip must be MJH, not "CEPAT"
    spec = FilenameSpec.parse("P002_BRJ_MDK_CEPAT.mp4")
    assert spec.directions == ("MDK", "MJH")
    assert spec.target_for(2).filename == "P002_BRJ_MJH_CEPAT_01.mp4"
    # different videos of one participant never share an output name
    a = FilenameSpec.parse("P002_BRJ_KKN_CEPAT.mp4").target_for(1).filename
    b = FilenameSpec.parse("P002_BRJ_KKN_NORMAL.mp4").target_for(1).filename
    assert a != b


def test_two_code_file_unchanged_and_every_code_pairs_with_its_reverse():
    two = FilenameSpec.parse("P001_BRJ_MDK_MJH_PELAN.mp4")
    assert two.directions == ("MDK", "MJH") and two.suffix == ["PELAN"]
    pairs = {"KKN": "KNK", "KNK": "KKN", "MDK": "MJH", "MJH": "MDK"}
    for code, rev in pairs.items():
        one = FilenameSpec.parse(f"P002_BRJ_{code}_NORMAL.mp4")
        assert one.directions == (code, rev)
        assert one.suffix == ["NORMAL"]
