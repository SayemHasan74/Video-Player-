"""Seek slider used by the control bar."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QSlider


class LightBeamSlider(QSlider):
    """Horizontal slider painted as a soft white light beam."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("QSlider { outline: none; background: transparent; }")

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = max(1, self.width())
        height = max(1, self.height())
        left = 10.0
        right = width - 10.0
        center_y = height / 2
        track_width = max(1.0, right - left)
        value_range = max(1, self.maximum() - self.minimum())
        progress = (self.value() - self.minimum()) / value_range
        progress_x = left + track_width * max(0.0, min(1.0, progress))

        base = QRectF(left, center_y - 2.0, track_width, 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        base_gradient = QLinearGradient(base.left(), base.top(), base.left(), base.bottom())
        base_gradient.setColorAt(0.0, QColor(255, 255, 255, 34))
        base_gradient.setColorAt(0.5, QColor(255, 255, 255, 18))
        base_gradient.setColorAt(1.0, QColor(0, 0, 0, 38))
        painter.setBrush(base_gradient)
        painter.drawRoundedRect(base, 2.0, 2.0)

        if progress_x > left:
            glow = QRectF(left - 8.0, center_y - 6.0, progress_x - left + 18.0, 12.0)
            glow_gradient = QLinearGradient(glow.left(), center_y, glow.right(), center_y)
            glow_gradient.setColorAt(0.0, QColor(255, 255, 255, 44))
            glow_gradient.setColorAt(0.68, QColor(255, 255, 255, 112))
            glow_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(glow_gradient)
            painter.drawRoundedRect(glow, 6.0, 6.0)

            beam = QRectF(left, center_y - 1.25, progress_x - left, 2.5)
            beam_gradient = QLinearGradient(beam.left(), beam.top(), beam.left(), beam.bottom())
            beam_gradient.setColorAt(0.0, QColor(255, 255, 255, 210))
            beam_gradient.setColorAt(0.45, QColor(255, 255, 255, 255))
            beam_gradient.setColorAt(1.0, QColor(210, 210, 210, 122))
            painter.setBrush(beam_gradient)
            painter.drawRoundedRect(beam, 1.25, 1.25)

            hot_spot = QRectF(max(left, progress_x - 28.0), center_y - 1.0, min(28.0, progress_x - left), 2.0)
            hot_gradient = QLinearGradient(hot_spot.left(), center_y, hot_spot.right(), center_y)
            hot_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            hot_gradient.setColorAt(1.0, QColor(255, 255, 255, 230))
            painter.setBrush(hot_gradient)
            painter.drawRoundedRect(hot_spot, 1.0, 1.0)

            reflection = QRectF(left, center_y + 3.0, progress_x - left, 2.4)
            reflection_gradient = QLinearGradient(reflection.left(), reflection.top(), reflection.left(), reflection.bottom())
            reflection_gradient.setColorAt(0.0, QColor(255, 255, 255, 58))
            reflection_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(reflection_gradient)
            painter.drawRoundedRect(reflection, 1.2, 1.2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 42))
        painter.drawEllipse(QRectF(progress_x - 7.0, center_y - 7.0, 14.0, 14.0))
        painter.setPen(QPen(QColor(255, 255, 255, 205), 0.8))
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.drawEllipse(QRectF(progress_x - 3.2, center_y - 3.2, 6.4, 6.4))


class SeekBar(LightBeamSlider):
    """Position slider with second-based signal."""

    seekRequested = pyqtSignal(float)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.duration = 0.0
        self._user_dragging = False
        self.setRange(0, 1000)
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
