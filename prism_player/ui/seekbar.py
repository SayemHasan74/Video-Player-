"""Seek slider used by the control bar."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter
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
        left = 5.0
        right = width - 5.0
        center_y = height / 2
        track_width = max(1.0, right - left)
        value_range = max(1, self.maximum() - self.minimum())
        progress = (self.value() - self.minimum()) / value_range
        progress_x = left + track_width * max(0.0, min(1.0, progress))

        # Recessed neutral rail.
        base = QRectF(left, center_y - 1.5, track_width, 3.0)
        painter.setPen(Qt.PenStyle.NoPen)
        base_gradient = QLinearGradient(base.left(), base.top(), base.left(), base.bottom())
        base_gradient.setColorAt(0.0, QColor(255, 255, 255, 28))
        base_gradient.setColorAt(0.5, QColor(255, 255, 255, 14))
        base_gradient.setColorAt(1.0, QColor(0, 0, 0, 70))
        painter.setBrush(base_gradient)
        painter.drawRoundedRect(base, 1.5, 1.5)

        if progress_x <= left:
            return

        # Diffuse halo: strongest near the live edge, fading cleanly outward.
        glow = QRectF(left, center_y - 5.0, progress_x - left + 7.0, 10.0)
        glow_vertical = QLinearGradient(0, glow.top(), 0, glow.bottom())
        glow_vertical.setColorAt(0.0, QColor(255, 255, 255, 0))
        glow_vertical.setColorAt(0.5, QColor(255, 255, 255, 48))
        glow_vertical.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(glow_vertical)
        painter.drawRoundedRect(glow, 5.0, 5.0)

        beam = QRectF(left, center_y - 1.0, progress_x - left, 2.0)
        beam_horizontal = QLinearGradient(beam.left(), center_y, beam.right(), center_y)
        beam_horizontal.setColorAt(0.0, QColor(170, 174, 180, 115))
        beam_horizontal.setColorAt(0.72, QColor(235, 240, 247, 215))
        beam_horizontal.setColorAt(1.0, QColor(255, 255, 255, 245))
        painter.setBrush(beam_horizontal)
        painter.drawRoundedRect(beam, 1.0, 1.0)

        # Small soft live edge, shown without a conventional slider knob.
        edge = QRectF(progress_x - 5.0, center_y - 3.5, 10.0, 7.0)
        edge_gradient = QLinearGradient(edge.left(), center_y, edge.right(), center_y)
        edge_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        edge_gradient.setColorAt(0.5, QColor(255, 255, 255, 135))
        edge_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(edge_gradient)
        painter.drawRoundedRect(edge, 3.5, 3.5)


class SeekBar(LightBeamSlider):
    """Position slider with second-based signal."""

    seekRequested = pyqtSignal(float)
    hoverRequested = pyqtSignal(float, QPoint)
    hoverEnded = pyqtSignal()

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.duration = 0.0
        self._user_dragging = False
        self.setRange(0, 1000)

    def set_duration(self, seconds: float) -> None:
        self.duration = max(0.0, float(seconds or 0.0))
        if self.duration <= 0 and not self._user_dragging:
            self.setValue(self.minimum())

    def set_position(self, seconds: float) -> None:
        if self._user_dragging or self.duration <= 0:
            return
        self.setValue(int((max(0.0, seconds) / self.duration) * 1000))

    def _value_at(self, x: float) -> int:
        left = 5.0
        track_width = max(1.0, self.width() - 10.0)
        ratio = max(0.0, min(1.0, (x - left) / track_width))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def _seek_to_mouse(self, event: QMouseEvent) -> None:
        if self.duration <= 0:
            return
        value = self._value_at(event.position().x())
        self.setValue(value)
        self.seekRequested.emit((value / 1000) * self.duration)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._user_dragging = True
            self._seek_to_mouse(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._user_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_to_mouse(event)
        if self.duration > 0:
            ratio = max(0.0, min(1.0, (event.position().x() - 5.0) / max(1.0, self.width() - 10.0)))
            self.hoverRequested.emit(ratio * self.duration, event.position().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._user_dragging:
            self._seek_to_mouse(event)
            self._user_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: object) -> None:
        self.hoverEnded.emit()
        super().leaveEvent(event)
