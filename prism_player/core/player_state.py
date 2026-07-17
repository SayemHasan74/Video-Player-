"""Authoritative main-thread cache of observed mpv state."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, Qt, pyqtSlot

from core.mpv_properties import DURATION, HWDEC, PAUSE, TIME_POS
from core.mpv_signals import MpvSignals


class PlayerState(QObject):
    """Cache populated only by queued slots on the Qt GUI thread."""

    def __init__(self, signals: MpvSignals, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.position = 0.0
        self.duration = 0.0
        self.paused = True
        self.file_is_loaded = False
        self.shutdown_received = False
        self.properties: dict[str, Any] = {}
        queued = Qt.ConnectionType.QueuedConnection
        signals.position_changed.connect(self.set_position, queued)
        signals.duration_changed.connect(self.set_duration, queued)
        signals.pause_changed.connect(self.set_paused, queued)
        signals.file_loaded.connect(self.mark_file_loaded, queued)
        signals.property_changed.connect(self.set_property, queued)
        signals.mpv_shutdown.connect(self.mark_shutdown, queued)

    @pyqtSlot(float)
    def set_position(self, value: float) -> None:
        self.position = float(value)
        self.properties[TIME_POS] = self.position

    @pyqtSlot(float)
    def set_duration(self, value: float) -> None:
        self.duration = float(value)
        self.properties[DURATION] = self.duration

    @pyqtSlot(bool)
    def set_paused(self, value: bool) -> None:
        self.paused = bool(value)
        self.properties[PAUSE] = self.paused

    @pyqtSlot()
    def mark_file_loaded(self) -> None:
        self.file_is_loaded = True

    @pyqtSlot(str, object)
    def set_property(self, name: str, value: object) -> None:
        if name == HWDEC and isinstance(value, list):
            value = value[0] if value else "no"
        self.properties[str(name)] = value

    @pyqtSlot()
    def mark_shutdown(self) -> None:
        self.shutdown_received = True
        self.file_is_loaded = False

    def get(self, name: str, fallback: Any = None) -> Any:
        value = self.properties.get(name, fallback)
        return fallback if value is None else value

    def set_local(self, name: str, value: Any) -> None:
        """Update the cache after a GUI-thread command without reading mpv."""
        self.properties[name] = value
        if name == TIME_POS:
            self.position = float(value or 0.0)
        elif name == DURATION:
            self.duration = float(value or 0.0)
        elif name == PAUSE:
            self.paused = bool(value)
