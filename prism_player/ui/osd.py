"""On-screen display label."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QLabel, QWidget


class OSDLabel(QLabel):
    """Temporary centered status message."""

    COLORS = {
        "info": "rgba(20,20,20,190)",
        "success": "rgba(18,70,35,210)",
        "warning": "rgba(90,70,20,220)",
        "error": "rgba(90,24,24,220)",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, level: str = "info", duration: int = 2200) -> None:
        self.setText(text)
        background = self.COLORS.get(level, self.COLORS["info"])
        self.setStyleSheet(
            f"QLabel {{ color: white; background: {background}; border-radius: 8px; padding: 10px 16px; font-weight: 600; }}"
        )
        self.adjustSize()
        if self.parentWidget() is not None:
            rect = self.parentWidget().rect()
            self.move((rect.width() - self.width()) // 2, max(56, rect.height() // 2 - 28))
        self.show()
        self.raise_()
        self.timer.start(duration)
