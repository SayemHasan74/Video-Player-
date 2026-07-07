"""Seek slider used by the control bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSlider


class SeekBar(QSlider):
    """Position slider with second-based signal."""

    seekRequested = pyqtSignal(float)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.duration = 0.0
        self._user_dragging = False
        self.setRange(0, 1000)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QSlider { outline: none; }")
        self.sliderPressed.connect(self._pressed)
        self.sliderReleased.connect(self._released)
        self.sliderMoved.connect(self._moved)

    def set_duration(self, seconds: float) -> None:
        self.duration = max(0.0, float(seconds or 0.0))

    def set_position(self, seconds: float) -> None:
        if self._user_dragging or self.duration <= 0:
            return
        self.setValue(int((max(0.0, seconds) / self.duration) * 1000))

    def _pressed(self) -> None:
        self._user_dragging = True

    def _released(self) -> None:
        self._user_dragging = False
        if self.duration > 0:
            self.seekRequested.emit((self.value() / 1000) * self.duration)

    def _moved(self, value: int) -> None:
        if self.duration > 0:
            self.seekRequested.emit((value / 1000) * self.duration)
