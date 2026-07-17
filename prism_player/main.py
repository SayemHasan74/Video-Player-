"""Comet Player application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
from core.dll_bootstrap import load_vendored_mpv, vendored_mpv_path

# Step 1: absolute ctypes.CDLL load. No Qt module is imported before this call.
_MPV_BOOTSTRAP_ERROR: Exception | None = None
try:
    load_vendored_mpv()
except (FileNotFoundError, OSError) as exc:
    _MPV_BOOTSTRAP_ERROR = exc

# Step 2: Qt imports happen only after the vendored DLL bootstrap.
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColorSpace, QIcon, QSurfaceFormat
from PyQt6.QtWidgets import QApplication, QMessageBox

from config.settings import APP_NAME, APP_VERSION, SettingsStore, global_stylesheet
from core.history_manager import HistoryManager


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
        f"Expected the vendored DLL at:\n{vendored_mpv_path()}\n\n"
        "Reinstall the application or restore bin\\mpv-2.dll.",
    )


def main(argv: list[str] | None = None) -> int:
    """Start Comet Player."""
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    settings = SettingsStore()
    settings.load()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    surface_format = QSurfaceFormat()
    surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface_format.setVersion(3, 3)
    surface_format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface_format.setSwapInterval(1)
    if settings.get("video.color_space", "srgb") == "display-p3":
        surface_format.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
    else:
        surface_format.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    QSurfaceFormat.setDefaultFormat(surface_format)
    # Step 3: construct QApplication.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(CURRENT_DIR / "assets" / "prism_logo.ico")))
    app.setStyleSheet(global_stylesheet())
    if _MPV_BOOTSTRAP_ERROR is not None:
        show_mpv_missing_dialog()
        return 1

    # Step 4: Qt may replace LC_NUMERIC, so restore C immediately after app creation.
    import locale

    locale.setlocale(locale.LC_NUMERIC, "C")

    # Step 5: import python-mpv through its sole owner only now.
    from core.mpv_engine import import_mpv_module

    import_mpv_module()

    # Importing the window graph after python-mpv preserves the bootstrap order;
    # the first MpvEngine created by PlayerWindowManager is step 6.
    from ui.player_window_manager import PlayerWindowManager

    history = HistoryManager()
    startup_files = normalize_startup_files(args.files)
    window_manager = PlayerWindowManager(settings, history)
    # QApplication does not own ordinary top-level Python wrappers. Keep the
    # lifecycle manager reachable for as long as the event loop is running.
    app.player_window_manager = window_manager  # type: ignore[attr-defined]
    window_manager.create_window(startup_files, args.url)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
