"""Ownership boundary for one player, playlist, history, and per-file state."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject

from core.media_state_store import MediaStateStore
from core.player_backend import PlayerBackend
from core.playlist_manager import PlaylistItem, PlaylistManager


class PlayerSession(QObject):
    """Own all mutable playback state for one Comet player window.

    Views may come and go (main, compact, PiP), but they all observe this one
    session.  Keeping timeline and current-item state here prevents mode or UI
    controllers from becoming competing sources of truth.
    """

    def __init__(self, video_widget: QObject, settings: Any, history: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.history = history
        self.playlist = PlaylistManager(self)
        self.player = PlayerBackend(video_widget, self, settings=settings)
        self.media_states = MediaStateStore()
        self.loaded_item: PlaylistItem | None = None
        # None follows automatic stream detection; True/False records the
        # user's explicit choice for this running player session.
        self.music_mode_manual_override: bool | None = None
        self._closed = False

    @property
    def position(self) -> float:
        return self.player.position

    @position.setter
    def position(self, value: float) -> None:
        self.player._position = float(value)

    @property
    def duration(self) -> float:
        return self.player.duration

    @duration.setter
    def duration(self, value: float) -> None:
        self.player._duration = float(value)

    def begin_item(self, item: PlaylistItem) -> float:
        previous = self.loaded_item
        if previous is not None and previous.source != item.source:
            self.save_position(previous)
        self.loaded_item = item
        self.position = 0.0
        self.duration = 0.0
        if self.settings.get("playback.remember_position", True):
            return float(self.history.resume_position(item.source) or 0.0)
        return 0.0

    def update_position(self, seconds: float) -> None:
        self.position = float(seconds)

    def update_duration(self, seconds: float) -> None:
        self.duration = float(seconds)

    def save_position(self, item: PlaylistItem | None = None) -> None:
        target = item or self.loaded_item
        if target is not None and self.settings.get("playback.remember_position", True):
            self.history.save_position(target.source, target.title, self.position, self.duration)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.save_position()
        self.player.shutdown()
        self.history.close()
