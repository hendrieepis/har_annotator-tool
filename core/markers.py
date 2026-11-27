"""Draggable start/stop markers and their meaning per walking direction.

Markers are two guide lines per axis, stored as fractions (0..1) of the frame:

* horizontal walking (left/right): ``x_left`` and ``x_right`` (vertical lines)
* depth walking (toward/away):     ``y_top``  and ``y_bottom`` (horizontal lines)

Which line is *start* and which is *stop* depends on the walking direction in
the file name (see :data:`DIRECTION_RULES`):

    KKN  kiri -> kanan   start = left line,   stop = right line
    KNK  kanan -> kiri   start = right line,  stop = left line
    MDK  mendekat        start = top line,    stop = bottom line
    MJH  menjauh         start = bottom line, stop = top line
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_GAP = 0.04  # lines may not get closer than 4% of the frame

# direction code -> (axis, sign). sign +1 = coordinate increases (left->right,
# top->bottom); -1 = decreases.
DIRECTION_RULES: dict[str, tuple[str, int]] = {
    "KKN": ("x", +1),
    "KNK": ("x", -1),
    "MDK": ("y", +1),
    "MJH": ("y", -1),
}

# axis -> {physical sense: direction code}. sense +1 = coordinate increases
# (left -> right, top -> bottom), -1 = decreases.
AXIS_CODES = {"x": {1: "KKN", -1: "KNK"}, "y": {1: "MDK", -1: "MJH"}}

# Which walking senses auto clip looks for.
MODE_FORWARD, MODE_REVERSE, MODE_BOTH = "forward", "reverse", "both"
MODES = (MODE_FORWARD, MODE_REVERSE, MODE_BOTH)
_MODE_SENSES = {MODE_FORWARD: (1,), MODE_REVERSE: (-1,), MODE_BOTH: (1, -1)}

# axis -> (low marker key, high marker key)
AXIS_KEYS = {"x": ("x_left", "x_right"), "y": ("y_top", "y_bottom")}


@dataclass
class MarkerSet:
    x_left: float = 0.25
    x_right: float = 0.75
    y_top: float = 0.65       # feet-based (see autoclip): lower half of frame
    y_bottom: float = 0.90
    # Reverse direction: swap which line is START and which is STOP. Needed when
    # a recording's naming (e.g. KNK first) is the mirror of the picture.
    flip: bool = False
    # Direction mode for auto clip: "forward" (left->right / top->bottom),
    # "reverse" (right->left / bottom->top) or "both" (default).
    mode: str = MODE_BOTH
    # Padding in seconds per line: whenever a walk STARTS or ENDS at that line
    # the clip is extended outward by this much. Needed at the far end of depth
    # walks (MDK/MJH), where the subject stands still and the operator starts or
    # stops a little earlier/later; the amount differs per recording. Default 0.
    # pad_lo = left / top line, pad_hi = right / bottom line.
    pad_lo: float = 0.0
    pad_hi: float = 0.0

    def get(self, key: str) -> float:
        return getattr(self, key)

    def move(self, key: str, value: float) -> None:
        """Move one line, clamped to the frame and kept apart from its partner."""
        value = min(max(value, 0.0), 1.0)
        lo_key, hi_key = next(k for k in AXIS_KEYS.values() if key in k)
        if key == lo_key:
            value = min(value, getattr(self, hi_key) - MIN_GAP)
        else:
            value = max(value, getattr(self, lo_key) + MIN_GAP)
        setattr(self, key, min(max(value, 0.0), 1.0))

    def pad_for(self, key: str) -> float:
        """Padding (s) for the line *key* (x_left/y_top -> pad_lo, else pad_hi)."""
        return self.pad_lo if key in ("x_left", "y_top") else self.pad_hi

    def axis_bounds(self, axis: str) -> tuple[float, float]:
        lo, hi = AXIS_KEYS[axis]
        return self.get(lo), self.get(hi)

    # -- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MarkerSet":
        m = cls()
        for key in ("x_left", "x_right", "y_top", "y_bottom"):
            if key in data:
                try:
                    setattr(m, key, float(data[key]))
                except (TypeError, ValueError):
                    pass
        m.flip = bool(data.get("flip", False))
        if data.get("mode") in MODES:
            m.mode = data["mode"]
        for key in ("pad_lo", "pad_hi"):
            try:
                setattr(m, key, min(max(float(data.get(key, 0.0)), 0.0), 30.0))
            except (TypeError, ValueError):
                pass
        # repair an inverted/degenerate file
        for lo, hi in AXIS_KEYS.values():
            if not (0.0 <= getattr(m, lo) < getattr(m, hi) <= 1.0):
                d = cls()
                setattr(m, lo, getattr(d, lo))
                setattr(m, hi, getattr(d, hi))
        return m

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "MarkerSet":
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError, AttributeError):
            return cls()


def start_stop_keys(direction: str, flip: bool = False) -> tuple[str, str] | None:
    """(start_key, stop_key) of the marker lines for *direction*, if known.

    ``flip`` reverses the walking sense (START and STOP swap lines)."""
    rule = DIRECTION_RULES.get(direction)
    if rule is None:
        return None
    axis, sign = rule
    lo, hi = AXIS_KEYS[axis]
    forward = (sign > 0) != flip
    return (lo, hi) if forward else (hi, lo)


def opposite_direction(code: str) -> str | None:
    """The reverse walk of *code* (KKN<->KNK, MDK<->MJH), or None if unknown."""
    rule = DIRECTION_RULES.get(code)
    if rule is None:
        return None
    axis, sense = rule
    return AXIS_CODES[axis][-sense]


def axes_in_use(spec_directions) -> list[str]:
    """Axes ("x"/"y") implied by the direction codes of the file name."""
    axes: list[str] = []
    for d in spec_directions:
        rule = DIRECTION_RULES.get(d)
        if rule and rule[0] not in axes:
            axes.append(rule[0])
    return axes


def active_directions(
    spec_directions, mode: str = MODE_BOTH, flip: bool = False
) -> list[tuple[str, str, int]]:
    """``[(code, axis, sense), ...]`` auto clip should look for.

    The axis comes from the file name (KKN/KNK -> x, MDK/MJH -> y); *mode*
    picks the walking sense(s). Clips are named by the direction actually
    walked, so a file called ``..._KKN_...`` yields both KKN and KNK clips in
    "both" mode. ``flip`` swaps the two codes for mirrored recordings.
    """
    out = []
    for axis in axes_in_use(spec_directions):
        for sense in _MODE_SENSES.get(mode, _MODE_SENSES[MODE_BOTH]):
            code = AXIS_CODES[axis][-sense if flip else sense]
            out.append((code, axis, sense))
    return out


def sense_keys(axis: str, sense: int) -> tuple[str, str]:
    """(start_key, stop_key) lines for walking *sense* along *axis*."""
    lo, hi = AXIS_KEYS[axis]
    return (lo, hi) if sense > 0 else (hi, lo)


def marker_roles(
    spec_directions, mode: str = MODE_BOTH, flip: bool = False
) -> dict[str, list[tuple[str, str]]]:
    """Which lines matter and what each one means.

    Returns ``{marker_key: [(direction, "START"|"STOP"), ...]}`` for the active
    directions only. Unknown file-name codes give an empty result.
    """
    roles: dict[str, list[tuple[str, str]]] = {}
    for code, axis, sense in active_directions(spec_directions, mode, flip):
        start, stop = sense_keys(axis, sense)
        roles.setdefault(start, []).append((code, "START"))
        roles.setdefault(stop, []).append((code, "STOP"))
    return roles
