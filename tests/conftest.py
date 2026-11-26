"""Make the repo importable as the ``har_annotator`` package.

The repo folder may have any name (e.g. ``har_annotator-tool``), so expose it
through ``.pkgroot/har_annotator -> ..`` (same trick the launcher uses).
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKGROOT = REPO / ".pkgroot"
PKGROOT.mkdir(exist_ok=True)
link = PKGROOT / "har_annotator"
if not link.is_symlink():
    os.symlink("..", link)
sys.path.insert(0, str(PKGROOT))
