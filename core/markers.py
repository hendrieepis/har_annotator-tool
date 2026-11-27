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
    # Extra seconds kept before the START line / after the STOP line. Operators
    # often begin a clip a little before the subject starts moving (and the
    # amount differs per recording), so this is a per-video setting, default 0.
    pre_roll: float = 0.0
    post_roll: float = 0.0

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
        for key in ("pre_roll", "post_roll"):
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


def marker_roles(directions, flip: bool = False) -> dict[str, list[tuple[str, str]]]:
    """Which lines matter for these directions and what each one means.

    Returns ``{marker_key: [(direction, "START"|"STOP"), ...]}``; only lines of
    axes actually used by *directions* are present. Unknown codes are ignored.
    """
    roles: dict[str, list[tuple[str, str]]] = {}
    for d in directions:
        keys = start_stop_keys(d, flip)
        if keys is None:
            continue
        start, stop = keys
        roles.setdefault(start, []).append((d, "START"))
        roles.setdefault(stop, []).append((d, "STOP"))
    return roles
