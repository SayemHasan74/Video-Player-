"""Seek slider used by the control bar."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QWheelEvent
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

        self._paint_track_decorations(painter, left, right, center_y)

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

    def _paint_track_decorations(
        self, painter: QPainter, left: float, right: float, center_y: float
    ) -> None:
        """Hook for seek-only buffer and chapter decorations."""


class SeekBar(LightBeamSlider):
    """Position slider with second-based signal."""

    seekPreviewRequested = pyqtSignal(float)
    seekRequested = pyqtSignal(float)
    hoverRequested = pyqtSignal(float, QPoint)
    hoverEnded = pyqtSignal()

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.duration = 0.0
        self._user_dragging = False
        self._buffered_ranges: list[tuple[float, float]] = []
        self._chapter_times: list[float] = []
        self._scroll_enabled = True
        self._pending_preview: float | None = None
        self._last_preview: float | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._flush_preview)
        self.setRange(0, 1000)

    def set_duration(self, seconds: float) -> None:
        self.duration = max(0.0, float(seconds or 0.0))
        if self.duration <= 0 and not self._user_dragging:
            self._preview_timer.stop()
            self._pending_preview = None
            self._last_preview = None
            self.setValue(self.minimum())

    def set_position(self, seconds: float) -> None:
        if self._user_dragging or self.duration <= 0:
            return
        self.setValue(int((max(0.0, seconds) / self.duration) * 1000))

    def set_buffered_ranges(self, ranges: list[tuple[float, float]]) -> None:
        self._buffered_ranges = [
            (max(0.0, float(start)), max(0.0, float(end)))
            for start, end in ranges
            if float(end) > float(start)
        ]
        self.update()

    def set_chapters(self, chapters: list[dict]) -> None:
        self._chapter_times = sorted(
            max(0.0, float(chapter.get("time", chapter.get("start", chapter.get("start_time", 0))) or 0))
            for chapter in chapters
        )
        self.update()

    def set_scroll_enabled(self, enabled: bool) -> None:
        self._scroll_enabled = bool(enabled)

    def _value_at(self, x: float) -> int:
        left = 5.0
        track_width = max(1.0, self.width() - 10.0)
        ratio = max(0.0, min(1.0, (x - left) / track_width))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def _position_from_mouse(self, event: QMouseEvent) -> float | None:
        if self.duration <= 0:
            return None
        value = self._value_at(event.position().x())
        self.setValue(value)
        return (value / 1000) * self.duration

    def _preview_now(self, seconds: float) -> None:
        self._pending_preview = None
        if self._last_preview is None or abs(seconds - self._last_preview) > 0.0001:
            self._last_preview = seconds
            self.seekPreviewRequested.emit(seconds)

    def _schedule_preview(self, seconds: float) -> None:
        self._pending_preview = seconds
        if not self._preview_timer.isActive():
            self._preview_timer.start()

    def _flush_preview(self) -> None:
        if self._pending_preview is not None:
            self._preview_now(self._pending_preview)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._user_dragging = True
            seconds = self._position_from_mouse(event)
            if seconds is not None:
                self._preview_now(seconds)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._user_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            seconds = self._position_from_mouse(event)
            if seconds is not None:
                self._schedule_preview(seconds)
        if self.duration > 0:
            ratio = max(0.0, min(1.0, (event.position().x() - 5.0) / max(1.0, self.width() - 10.0)))
            self.hoverRequested.emit(ratio * self.duration, event.position().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._user_dragging:
            seconds = self._position_from_mouse(event)
            self._preview_timer.stop()
            if seconds is not None:
                # Land on the latest dragged position immediately, then let the
                # backend perform one accurate seek after input settles.
                self._preview_now(seconds)
                self.seekRequested.emit(seconds)
            self._user_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: object) -> None:
        self.hoverEnded.emit()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._scroll_enabled or self.duration <= 0:
            event.ignore()
            return
        steps = event.angleDelta().y() / 120.0
        current = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum()) * self.duration
        target = max(0.0, min(self.duration, current + steps * 5.0))
        self.setValue(round(target / self.duration * 1000))
        self._preview_now(target)
        self.seekRequested.emit(target)
        event.accept()

    def _paint_track_decorations(
        self, painter: QPainter, left: float, right: float, center_y: float
    ) -> None:
        if self.duration <= 0:
            return
        track_width = max(1.0, right - left)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(210, 220, 232, 62))
        for start, end in self._buffered_ranges:
            x1 = left + track_width * min(1.0, start / self.duration)
            x2 = left + track_width * min(1.0, end / self.duration)
            if x2 > x1:
                painter.drawRoundedRect(QRectF(x1, center_y - 1.5, x2 - x1, 3.0), 1.5, 1.5)
        painter.setBrush(QColor(245, 245, 245, 150))
        for chapter_time in self._chapter_times:
            if chapter_time <= 0 or chapter_time >= self.duration:
                continue
            x = left + track_width * chapter_time / self.duration
            painter.drawRoundedRect(QRectF(x - 0.75, center_y - 4.0, 1.5, 8.0), 0.75, 0.75)
