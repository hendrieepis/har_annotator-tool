"""Filename parsing and output-name generation for the HAR annotation tool.

A raw recording packs two walking directions that alternate back and forth (or a
single direction, see below), e.g.

    P001_BRJ_KKN_KNK_NORMAL.mp4   ->  KKN, KNK, KKN, KNK, ...

The two direction codes sit at a fixed pair of token positions (default index
2 and 3). Everything before them is a *prefix* (participant, activity), and
everything after is a *suffix* (e.g. speed). Output clips replace the two
direction codes with a single direction plus a 2-digit repetition number, while
keeping the order in which the directions appear in the source name:

    clip 1 -> P001_BRJ_KKN_NORMAL_01.mp4
    clip 2 -> P001_BRJ_KNK_NORMAL_01.mp4
    clip 3 -> P001_BRJ_KKN_NORMAL_02.mp4
    ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .markers import DIRECTION_RULES

# A recording may also hold a SINGLE direction (e.g. P001_BRJ_KKN_CEPAT.mp4):
# when the token after the first direction is not a known direction code, it is
# part of the suffix and every clip uses that one direction:
#
#     P001_BRJ_KKN_CEPAT.mp4  ->  P001_BRJ_KKN_CEPAT_01.mp4, _02.mp4, ...


@dataclass(frozen=True)
class ClipTarget:
    """The identity of one output clip, derived purely from its global index."""

    index: int          # 1-based running index across both directions
    direction: str      # e.g. "KKN"
    repetition: int     # 1-based repetition number for this direction
    filename: str       # full output file name including extension


@dataclass
class FilenameSpec:
    """Decomposes a raw source filename into its semantic parts.

    Attributes mirror the token layout so the UI can display and, if a recording
    deviates from the convention, override them before exporting.
    """

    prefix: list[str]
    directions: tuple[str, ...]   # 1 (single direction) or 2 (alternating)
    suffix: list[str]
    extension: str
    # 0-based positions of the two direction tokens in the original stem.
    direction_positions: tuple[int, ...] = (2, 3)

    DIR1_POS = 2
    DIR2_POS = 3

    @classmethod
    def parse(cls, filename: str | Path) -> "FilenameSpec":
        path = Path(filename)
        stem = path.stem
        ext = path.suffix or ".mp4"
        tokens = stem.split("_")
        p1, p2 = cls.DIR1_POS, cls.DIR2_POS
        known = DIRECTION_RULES
        if (
            len(tokens) > p1
            and tokens[p1] in known
            and (len(tokens) <= p2 or tokens[p2] not in known)
        ):
            # single-direction recording: PREFIX_DIR_SUFFIX
            return cls(
                prefix=tokens[:p1],
                directions=(tokens[p1],),
                suffix=tokens[p1 + 1:],
                extension=ext,
                direction_positions=(p1,),
            )
        if len(tokens) <= p2:
            raise ValueError(
                f"Filename '{path.name}' does not match the expected pattern "
                f"PREFIX_DIR1_DIR2_SUFFIX (need at least {p2 + 1} '_'-separated "
                f"tokens, found {len(tokens)})."
            )
        prefix = tokens[:p1]
        directions = (tokens[p1], tokens[p2])
        suffix = tokens[p2 + 1:]
        return cls(
            prefix=prefix,
            directions=directions,
            suffix=suffix,
            extension=ext,
            direction_positions=(p1, p2),
        )

    def target_for(self, index: int) -> ClipTarget:
        """Return the output identity for the *index*-th saved clip (1-based)."""
        if index < 1:
            raise ValueError("clip index is 1-based and must be >= 1")
        n = len(self.directions)
        direction = self.directions[(index - 1) % n]
        repetition = (index - 1) // n + 1
        tokens = [*self.prefix, direction, *self.suffix, f"{repetition:02d}"]
        filename = "_".join(tokens) + self.extension
        return ClipTarget(
            index=index,
            direction=direction,
            repetition=repetition,
            filename=filename,
        )

    def preview(self, count: int) -> list[ClipTarget]:
        """First *count* output targets, useful for showing the plan up front."""
        return [self.target_for(i) for i in range(1, count + 1)]
