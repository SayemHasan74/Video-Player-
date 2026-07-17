"""The sole cross-thread bridge from python-mpv callbacks into Qt."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class MpvSignals(QObject):
    """Signals emitted by callbacks running on python-mpv's event thread."""

    position_changed = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    pause_changed = pyqtSignal(bool)
    file_loaded = pyqtSignal()
    render_update = pyqtSignal()
    property_changed = pyqtSignal(str, object)
    mpv_shutdown = pyqtSignal()
    log_message = pyqtSignal(str, str)
