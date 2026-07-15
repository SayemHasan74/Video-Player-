"""On-screen status and mpv-driven buffering overlays."""

from __future__ import annotations

import math
from typing import Any

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from utils.accessibility import transitions_enabled


class OSDLabel(QLabel):
    """Categorized, suppressible, dismissible player status message."""

    COLORS = {
        "info": "rgba(20,20,20,190)",
        "success": "rgba(18,70,35,210)",
        "warning": "rgba(90,70,20,220)",
        "error": "rgba(90,24,24,220)",
    }

    def __init__(self, parent: QWidget | None = None, settings: Any | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()
        self.enabled = True
        self.category = "general"
        self.dismissible = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.hide()

    def configure(self) -> None:
        self.set_enabled(bool(self.settings.get("ui.show_osd", True)) if self.settings else True)
        if self.isVisible():
            self.reposition()

    def show_message(
        self,
        text: str,
        level: str = "info",
        duration: int = 2200,
        *,
        category: str = "general",
        dismissible: bool = True,
    ) -> bool:
        normalized_category = str(category or "general").strip().casefold()
        if not self.enabled or self._is_suppressed(normalized_category):
            return False
        self.category = normalized_category
        self.dismissible = bool(dismissible)
        self.timer.stop()
        if not text:
            self.hide()
            return False
        self.setAccessibleName("Player status")
        self.setAccessibleDescription(text)
        self.setText(text)
        background = self.COLORS.get(level, self.COLORS["info"])
        self.setStyleSheet(
            f"QLabel {{ color: white; background: {background}; border-radius: 8px; padding: 10px 16px; font-weight: 600; }}"
        )
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        if duration > 0:
            self.timer.start(int(duration))
        return True

    def dismiss(self, category: str | None = None) -> bool:
        if not self.isVisible() or not self.dismissible:
            return False
        if category is not None and self.category != str(category).casefold():
            return False
        self.timer.stop()
        self.hide()
        return True

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        rect = parent.rect()
        position = str(self.settings.get("ui.osd_position", "top") if self.settings else "top")
        x = max(8, (rect.width() - self.width()) // 2)
        if position == "bottom":
            y = max(8, rect.height() - self.height() - 72)
        elif position == "center":
            y = max(8, (rect.height() - self.height()) // 2)
        else:
            y = max(8, min(72, rect.height() - self.height() - 8))
        self.move(x, y)

    def _is_suppressed(self, category: str) -> bool:
        if self.settings is None:
            return False
        raw = self.settings.get("ui.osd_suppressed_categories", "")
        if isinstance(raw, str):
            suppressed = {entry.strip().casefold() for entry in raw.split(",") if entry.strip()}
        elif isinstance(raw, (list, tuple, set)):
            suppressed = {str(entry).strip().casefold() for entry in raw if str(entry).strip()}
        else:
            suppressed = set()
        return category in suppressed or "all" in suppressed


class _Spinner(QWidget):
    def __init__(self, settings: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.angle = 0
        self.setFixedSize(26, 26)
        self.timer = QTimer(self)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self._advance)

    def start(self) -> None:
        if transitions_enabled(self.settings):
            self.timer.start()
        else:
            self.timer.stop()
            self.angle = 0
            self.update()

    def stop(self) -> None:
        self.timer.stop()

    def _advance(self) -> None:
        self.angle = (self.angle + 30) % 360
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 - 4
        for index in range(12):
            angle = math.radians(index * 30 + self.angle)
            start = QPointF(center.x() + math.cos(angle) * (radius - 4), center.y() + math.sin(angle) * (radius - 4))
            end = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
            alpha = 55 + round(190 * (index + 1) / 12)
            painter.setPen(QPen(QColor(245, 245, 245, alpha), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)


class BufferingIndicator(QWidget):
    """Subtle indicator controlled only by the backend's mpv state signal."""

    def __init__(self, settings: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.active = False
        self.mode = "spinner"
        self.spinner = _Spinner(settings, self)
        self.label = QLabel("Buffering…", self)
        self.label.setStyleSheet("background:transparent;color:#f3f3f3;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        layout.addWidget(self.spinner)
        layout.addWidget(self.label)
        self.setStyleSheet("background:rgba(8,8,8,180);border:1px solid rgba(255,255,255,28);border-radius:18px;")
        self.setAccessibleName("Buffering")
        self.hide()
        self.apply_preferences()

    def apply_preferences(self) -> None:
        mode = str(self.settings.get("ui.buffering_throbber", "spinner")).casefold()
        self.mode = mode if mode in {"off", "spinner", "text", "both"} else "spinner"
        self.spinner.setVisible(self.mode in {"spinner", "both"})
        self.label.setVisible(self.mode in {"text", "both"})
        self.adjustSize()
        self.set_active(self.active)

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        visible = self.active and self.mode != "off"
        if visible and self.mode in {"spinner", "both"}:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.setVisible(visible)
        if visible:
            self.raise_()
