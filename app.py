"""Application entry point."""

from __future__ import annotations

import os
import sys


def _ensure_qt_plugin_path() -> None:
    """Point Qt at PySide6's own plugins.

    In a conda/base environment another Qt (e.g. the one bundled with
    conda's opencv) can shadow PySide6's, leaving the platform plugin search
    path empty -> "Could not find the Qt platform plugin xcb in ''". We set the
    paths from PySide6's known location *before* any Qt module is imported.
    """
    import PySide6

    plugins = os.path.join(os.path.dirname(PySide6.__file__), "Qt", "plugins")
    if os.path.isdir(plugins):
        os.environ.setdefault(
            "QT_QPA_PLATFORM_PLUGIN_PATH", os.path.join(plugins, "platforms")
        )
        os.environ.setdefault("QT_PLUGIN_PATH", plugins)


def main() -> int:
    _ensure_qt_plugin_path()

    from PySide6.QtWidgets import QApplication

    from har_annotator.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("HAR Dataset Annotator")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
