"""Platform-correct drag classification for the native video area."""

from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication


def drag_threshold_reached(origin: QPoint, current: QPoint) -> bool:
    """Return whether a pointer moved far enough to become a drag."""
    return (current - origin).manhattanLength() >= QApplication.startDragDistance()
