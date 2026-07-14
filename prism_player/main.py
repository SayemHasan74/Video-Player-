"""Comet Player application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon, QSurfaceFormat
from PyQt6.QtWidgets import QApplication, QMessageBox

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
_DLL_DIRECTORY_HANDLES = []
for dll_dir in (CURRENT_DIR, CURRENT_DIR.parent):
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory") and dll_dir.exists():
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))

from config.settings import APP_NAME, APP_VERSION, SettingsStore, global_stylesheet
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from ui.main_window import MainWindow


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("files", nargs="*", help="Media files to open")
    parser.add_argument("--url", default="", help="Online media URL to open")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


def normalize_startup_files(raw_files: list[str]) -> list[Path]:
    """Recover file paths even if a weak launcher split a path at spaces."""
    files: list[Path] = []
    index = 0
    while index < len(raw_files):
        candidate = Path(raw_files[index]).expanduser()
        if candidate.exists():
            files.append(candidate.resolve())
            index += 1
            continue
        combined = raw_files[index]
        recovered: Path | None = None
        recovered_index = index
        for next_index in range(index + 1, len(raw_files)):
            combined = f"{combined} {raw_files[next_index]}"
            combined_path = Path(combined).expanduser()
            if combined_path.exists():
                recovered = combined_path.resolve()
                recovered_index = next_index
                break
        files.append(recovered if recovered is not None else candidate.resolve())
        index = recovered_index + 1
    return files


def show_mpv_missing_dialog() -> None:
    """Show instructions for installing mpv."""
    QMessageBox.critical(
        None,
        "mpv-2.dll not found",
        f"{APP_NAME} needs mpv-2.dll to play media.\n\n"
        f"Place mpv-2.dll or libmpv-2.dll beside main.py or anywhere on PATH, then run {APP_NAME} again.",
    )


def main(argv: list[str] | None = None) -> int:
    """Start Comet Player."""
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    surface_format = QSurfaceFormat()
    surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface_format.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(CURRENT_DIR / "assets" / "prism_logo.ico")))
    app.setStyleSheet(global_stylesheet())
    if not PlayerBackend.mpv_dll_exists(CURRENT_DIR):
        show_mpv_missing_dialog()
        return 1
    settings = SettingsStore()
    settings.load()
    history = HistoryManager()
    startup_files = normalize_startup_files(args.files)
    window = MainWindow(settings, history, startup_files, args.url)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
