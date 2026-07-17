"""Lifecycle owner for independent player windows in one application process."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt

from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.media_probe import probe_media
from ui.geometry import video_aspect_from_probe

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class PlayerWindowManager(QObject):
    """Create player sessions and retain them until their windows are destroyed."""

    def __init__(self, settings: SettingsStore, history: HistoryManager) -> None:
        super().__init__()
        self._settings = settings
        self._history_path = history.path
        self._initial_history: HistoryManager | None = history
        self._windows: list[MainWindow] = []

    @property
    def windows(self) -> tuple[MainWindow, ...]:
        return tuple(self._windows)

    def create_window(
        self,
        files: list[Path] | None = None,
        url: str = "",
        force_current: bool = False,
    ) -> MainWindow:
        # Local import avoids a cycle: MainWindow only depends on this object
        # through its small open_paths/open_url interface.
        from ui.main_window import MainWindow

        if self._initial_history is not None:
            history = self._initial_history
            self._initial_history = None
        else:
            history = HistoryManager(self._history_path)
        previous = self._windows[-1] if self._windows else None
        initial_source = str(files[0]) if files else ""
        initial_aspect = (
            video_aspect_from_probe(probe_media(initial_source))
            if initial_source and Path(initial_source).is_file()
            else 0.0
        )
        window = MainWindow(
            self._settings,
            history,
            files or [],
            url,
            window_manager=self,
            force_startup_current=force_current,
            startup_scan_siblings=not force_current,
            initial_aspect=initial_aspect,
            initial_source=initial_source,
            defer_startup_open=bool(files or url),
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._windows.append(window)
        window.destroyed.connect(lambda _object=None, target=window: self._forget(target))
        if previous is not None and not window.isMaximized() and not window.isFullScreen():
            window.move(previous.pos().x() + 28, previous.pos().y() + 28)
        startup_loaded = False

        def load_startup() -> None:
            nonlocal startup_loaded
            if startup_loaded:
                return
            startup_loaded = True
            if url:
                window.open_url(url, apply_behavior=not force_current)
            elif files:
                window.open_files(
                    files,
                    append=False if force_current else None,
                    scan_siblings=not force_current,
                )

        if files or url:
            window.video.rendererReady.connect(
                load_startup,
                Qt.ConnectionType.SingleShotConnection,
            )
        window._show_startup_window()
        if (files or url) and window.video.renderer_active:
            load_startup()
        return window

    def open_paths(self, paths: list[Path]) -> MainWindow:
        return self.create_window(list(paths), force_current=True)

    def open_url(self, url: str) -> MainWindow:
        return self.create_window(url=url, force_current=True)

    def _forget(self, window: MainWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
