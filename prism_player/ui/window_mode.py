"""Explicit player-window mode state and transition ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from PyQt6.QtCore import QObject, QRect, pyqtSignal

from config.settings import CONTROL_BAR_HEIGHT, MIN_WINDOW_SIZE, TITLE_BAR_HEIGHT

APP_MENU_HEIGHT = 32
COMPACT_PLAYER_HEIGHT = 140


class WindowMode(Enum):
    NORMAL = auto()
    MAXIMIZED = auto()
    FULLSCREEN = auto()
    COMPACT = auto()
    PIP = auto()


class FullscreenState(Enum):
    WINDOWED = auto()
    ANIMATING_TO_FULLSCREEN = auto()
    FULLSCREEN = auto()
    ANIMATING_TO_WINDOWED = auto()


@dataclass(frozen=True)
class WindowSnapshot:
    mode: WindowMode
    geometry: QRect
    playlist_visible: bool
    chrome_visible: bool


class WindowModeController(QObject):
    """Perform atomic window-mode transitions without geometry retry timers."""

    modeChanged = pyqtSignal(object)

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.mode = WindowMode.NORMAL
        self.compact_snapshot: WindowSnapshot | None = None
        self.fullscreen_snapshot: WindowSnapshot | None = None
        self.pip_snapshot: WindowSnapshot | None = None
        self.transitioning = False
        self.fullscreen_state = FullscreenState.WINDOWED
        self._pending_fullscreen_exit = False

    @property
    def is_compact(self) -> bool:
        return self.mode is WindowMode.COMPACT

    @property
    def is_pip(self) -> bool:
        return self.mode is WindowMode.PIP

    def sync_from_window(self) -> None:
        if self.is_compact or self.is_pip:
            return
        self.mode = self._native_mode()
        if self.fullscreen_state not in {
            FullscreenState.ANIMATING_TO_FULLSCREEN,
            FullscreenState.ANIMATING_TO_WINDOWED,
        }:
            self.fullscreen_state = (
                FullscreenState.FULLSCREEN if self.window.isFullScreen() else FullscreenState.WINDOWED
            )

    def toggle_compact(self) -> None:
        if self.transitioning:
            return
        if self.is_compact:
            self.exit_compact()
        else:
            self.enter_compact()

    def enter_compact(self) -> None:
        if self.transitioning or self.is_compact:
            return
        if self.is_pip:
            self.exit_pip()
        self._begin()
        try:
            self.sync_from_window()
            self.compact_snapshot = self._snapshot()
            previous = self.compact_snapshot.geometry
            self.mode = WindowMode.COMPACT
            self._hide_playlist()
            if self.window.isFullScreen() or self.window.isMaximized():
                self.window.showNormal()
            music_mode = getattr(self.window, "music_mode", None)
            if music_mode is not None:
                music_mode.enter_layout()
            compact_height = (
                music_mode.target_height()
                if music_mode is not None
                else max(
                    COMPACT_PLAYER_HEIGHT,
                    TITLE_BAR_HEIGHT + APP_MENU_HEIGHT + CONTROL_BAR_HEIGHT,
                )
            )
            self.window.setMaximumHeight(16777215)
            self.window.setMinimumSize(520 if music_mode is not None else 420, compact_height)
            self.window.setMaximumHeight(compact_height)
            self.window.setGeometry(
                previous.left(),
                previous.top(),
                max(520 if music_mode is not None else 420, previous.width()),
                compact_height,
            )
            self.window.control_bar.set_fullscreen(False)
            self.window._chrome_visible = True
            self.window._apply_mode_layout()
        finally:
            self._finish()

    def exit_compact(self) -> None:
        if self.transitioning or not self.is_compact:
            return
        self._begin()
        try:
            snapshot = self.compact_snapshot or WindowSnapshot(
                WindowMode.NORMAL, QRect(self.window.geometry()), False, True
            )
            music_mode = getattr(self.window, "music_mode", None)
            if music_mode is not None:
                music_mode.exit_layout()
            self.window.setMaximumHeight(16777215)
            self.window.setMinimumSize(*MIN_WINDOW_SIZE)
            self.mode = snapshot.mode
            self._restore_native_state(snapshot)
            self._restore_ui(snapshot)
            self.compact_snapshot = None
        finally:
            self._finish()

    def toggle_fullscreen(self) -> None:
        if self.fullscreen_state in {
            FullscreenState.ANIMATING_TO_FULLSCREEN,
            FullscreenState.ANIMATING_TO_WINDOWED,
        } or self.transitioning:
            return
        if self.is_pip:
            self.exit_pip()
        if self.is_compact:
            self.exit_compact()
        self._begin()
        if self.fullscreen_state is FullscreenState.FULLSCREEN or self.window.isFullScreen():
            self.fullscreen_state = FullscreenState.ANIMATING_TO_WINDOWED
            snapshot = self.fullscreen_snapshot or WindowSnapshot(
                WindowMode.NORMAL, QRect(self.window.normalGeometry()), False, True
            )
            self.mode = snapshot.mode

            def change() -> None:
                self._restore_native_state(snapshot)
                self._restore_ui(snapshot)
                self.fullscreen_snapshot = None

            def complete() -> None:
                self.fullscreen_state = FullscreenState.WINDOWED
                self._finish()
        else:
            self.sync_from_window()
            self.fullscreen_snapshot = self._snapshot()
            self.fullscreen_state = FullscreenState.ANIMATING_TO_FULLSCREEN
            self._hide_playlist()

            def change() -> None:
                self.window.showFullScreen()
                self.window.control_bar.set_fullscreen(True)
                self.window._chrome_visible = True
                self.window._apply_mode_layout()

            def complete() -> None:
                self.mode = WindowMode.FULLSCREEN
                self.fullscreen_state = FullscreenState.FULLSCREEN
                self._finish()
                if self._pending_fullscreen_exit:
                    self._pending_fullscreen_exit = False
                    self.exit_fullscreen()

        animate = getattr(self.window, "_animate_fullscreen_change", None)
        if callable(animate):
            animate(change, complete)
        else:
            change()
            complete()

    def exit_fullscreen(self) -> None:
        """Exit fullscreen from every transition state; Esc uses this path."""
        if self.fullscreen_state is FullscreenState.ANIMATING_TO_FULLSCREEN:
            self._pending_fullscreen_exit = True
            return
        if self.fullscreen_state is FullscreenState.ANIMATING_TO_WINDOWED:
            return
        if self.fullscreen_state is FullscreenState.FULLSCREEN or self.window.isFullScreen():
            self.toggle_fullscreen()

    def toggle_maximized(self) -> None:
        if self.transitioning:
            return
        if self.is_pip:
            self.exit_pip()
        if self.is_compact:
            self.exit_compact()
        self._begin()
        try:
            if self.window.isMaximized():
                self.window.showNormal()
                self.mode = WindowMode.NORMAL
            else:
                self.window.showMaximized()
                self.mode = WindowMode.MAXIMIZED
            self.window.title_bar.set_maximized(self.window.isMaximized())
            self.window._apply_mode_layout()
        finally:
            self._finish()

    def toggle_pip(self) -> None:
        if self.transitioning:
            return
        if self.is_pip:
            self.exit_pip()
        else:
            self.enter_pip()

    def enter_pip(self) -> None:
        if self.transitioning or self.is_pip:
            return
        pip_window = getattr(self.window, "pip_window", None)
        if pip_window is None:
            return
        if self.is_compact:
            self.exit_compact()
        self._begin()
        try:
            self.sync_from_window()
            self.pip_snapshot = self._snapshot()
            self.mode = WindowMode.PIP
            self._hide_playlist()
            pip_window.attach_video(self.window.video)
            self.window.hide()
            pip_window.show_for_screen(self.window.screen())
        finally:
            self._finish()

    def exit_pip(self) -> None:
        if self.transitioning or not self.is_pip:
            return
        self._begin()
        try:
            snapshot = self.pip_snapshot or WindowSnapshot(
                WindowMode.NORMAL, QRect(self.window.normalGeometry()), False, True
            )
            pip_window = self.window.pip_window
            pip_window.save_geometry()
            pip_window.detach_video(self.window.central_shell)
            pip_window.hide()
            self.mode = snapshot.mode
            self._restore_native_state(snapshot)
            self._restore_ui(snapshot)
            self.window.video.show()
            self.window.raise_()
            self.window.activateWindow()
            self.pip_snapshot = None
        finally:
            self._finish()

    def _begin(self) -> None:
        self.transitioning = True
        self.window._prepare_mode_transition()

    def _finish(self) -> None:
        self.transitioning = False
        if not self.is_pip:
            self.window._position_overlays()
        video = getattr(self.window, "video", None)
        if video is not None and hasattr(video, "ensure_renderer"):
            video.ensure_renderer()
        self.modeChanged.emit(self.mode)

    def _snapshot(self) -> WindowSnapshot:
        native_mode = self._native_mode()
        geometry = self.window.geometry() if native_mode is WindowMode.NORMAL else self.window.normalGeometry()
        return WindowSnapshot(
            mode=native_mode,
            geometry=QRect(geometry),
            playlist_visible=(self.window.sidebars.playlist_open if hasattr(self.window, "sidebars") else self.window.playlist_panel.isVisible()),
            chrome_visible=bool(self.window._chrome_visible),
        )

    def _native_mode(self) -> WindowMode:
        if self.window.isFullScreen():
            return WindowMode.FULLSCREEN
        if self.window.isMaximized():
            return WindowMode.MAXIMIZED
        return WindowMode.NORMAL

    def _hide_playlist(self) -> None:
        if hasattr(self.window, "sidebars"):
            self.window.sidebars.set_playlist_visible(False, animate=False, persist=False)
        else:
            self.window.playlist_panel.hide()
        self.window.control_bar.set_playlist_visible(False)

    def _restore_native_state(self, snapshot: WindowSnapshot) -> None:
        if snapshot.mode is WindowMode.FULLSCREEN:
            self.window.showNormal()
            if snapshot.geometry.isValid():
                self.window.setGeometry(snapshot.geometry)
            self.window.showFullScreen()
            self.window.control_bar.set_fullscreen(True)
        elif snapshot.mode is WindowMode.MAXIMIZED:
            self.window.showNormal()
            if snapshot.geometry.isValid():
                self.window.setGeometry(snapshot.geometry)
            self.window.showMaximized()
            self.window.control_bar.set_fullscreen(False)
        else:
            self.window.showNormal()
            self.window.setGeometry(snapshot.geometry)
            self.window.control_bar.set_fullscreen(False)

    def _restore_ui(self, snapshot: WindowSnapshot) -> None:
        self.window._chrome_visible = snapshot.chrome_visible
        if hasattr(self.window, "sidebars"):
            self.window.sidebars.set_playlist_visible(snapshot.playlist_visible, animate=False, persist=False)
        elif snapshot.playlist_visible:
            self.window.playlist_panel.show()
            self.window.control_bar.set_playlist_visible(True)
        else:
            self.window.playlist_panel.hide()
            self.window.control_bar.set_playlist_visible(False)
        self.window._apply_mode_layout()
