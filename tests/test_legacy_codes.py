"""Old spellings KKN / KNK still work in input names and sidecars, output uses
KRKN (kiri ke kanan) / KNKR (kanan ke kiri)."""

import json
from pathlib import Path

from har_annotator.core.markers import (
    DIRECTION_RULES,
    MarkerSet,
    canonical_direction,
    marker_roles,
    start_stop_keys,
)
from har_annotator.core.naming import FilenameSpec
from har_annotator.core.session import AnnotationSession


def test_canonical_codes():
    assert canonical_direction("KKN") == "KRKN"
    assert canonical_direction("KNK") == "KNKR"
    assert canonical_direction("KRKN") == "KRKN"
    assert canonical_direction("MDK") == "MDK" and canonical_direction("XYZ") == "XYZ"
    assert DIRECTION_RULES["KKN"] == DIRECTION_RULES["KRKN"]
    assert start_stop_keys("KNK") == start_stop_keys("KNKR") == ("x_right", "x_left")


def test_two_code_legacy_name_is_written_with_new_codes():
    spec = FilenameSpec.parse("P001_BRJ_KKN_KNK_NORMAL.mp4")
    assert spec.directions == ("KRKN", "KNKR")
    assert [spec.target_for(i).filename for i in (1, 2, 3)] == [
        "P001_BRJ_KRKN_NORMAL_01.mp4",
        "P001_BRJ_KNKR_NORMAL_01.mp4",
        "P001_BRJ_KRKN_NORMAL_02.mp4",
    ]
    swapped = FilenameSpec.parse("P001_BRJ_KNK_KKN_NORMAL.mp4")   # KNK first
    assert swapped.target_for(1).filename == "P001_BRJ_KNKR_NORMAL_01.mp4"


def test_one_code_legacy_and_new_names_agree():
    old = FilenameSpec.parse("P001_BRJ_KKN_CEPAT.mp4")
    new = FilenameSpec.parse("P001_BRJ_KRKN_CEPAT.mp4")
    assert old.directions == new.directions == ("KRKN", "KNKR")
    assert old.target_for(2).filename == "P001_BRJ_KNKR_CEPAT_01.mp4"
    assert FilenameSpec.parse("P002_BRJ_MDK_CEPAT.mp4").target_for(2).filename == (
        "P002_BRJ_MJH_CEPAT_01.mp4"
    )


def test_labels_use_new_codes_whatever_the_file_spelling():
    for name in ("KKN", "KRKN"):
        roles = marker_roles(FilenameSpec.parse(f"P001_BRJ_{name}_CEPAT.mp4").directions)
        assert roles["x_left"] == [("KRKN", "START"), ("KNKR", "STOP")]
    assert MarkerSet().mode == "both"


def test_old_state_files_are_read_with_new_direction_codes(tmp_path):
    src = tmp_path / "P001_BRJ_KKN_KNK_CEPAT.mp4"
    spec = FilenameSpec.parse(src)
    s = AnnotationSession.load_or_create(src, tmp_path, spec)
    state = s._exported_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"clips": [{
        "index": 1, "direction": "KKN", "repetition": 1,
        "start_frame": 5, "end_frame": 50, "filename": "P001_BRJ_KKN_CEPAT_01.mp4",
    }]}))
    again = AnnotationSession.load_or_create(src, tmp_path, spec)
    rec = again.exported[0]
    assert rec.direction == "KRKN"                      # normalised ...
    assert rec.filename == "P001_BRJ_KKN_CEPAT_01.mp4"  # ... file on disk untouched
    # repetition counting continues across old + new records of one direction
    new = again.add_mark(60, 90, direction="KRKN")
    assert new.repetition == 2 and new.filename == "P001_BRJ_KRKN_CEPAT_02.mp4"
