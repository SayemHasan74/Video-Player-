"""Custom frameless title bar."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

from assets.icons import svg_icon
from config.settings import APP_SHORT_NAME, TITLE_BAR_HEIGHT


class TitleBar(QWidget):
    """Windows-style custom title bar."""

    minimizeClicked = pyqtSignal()
    maximizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()
    dragStarted = pyqtSignal(QPoint)
    dragMoved = pyqtSignal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setMinimumHeight(TITLE_BAR_HEIGHT)
        self.setMaximumHeight(TITLE_BAR_HEIGHT)
        self.setStyleSheet(
            """
            TitleBar {
                background: #0d0d0d;
                border-bottom: 1px solid #252525;
            }
            QLabel { background: transparent; }
            TitleBar QPushButton {
                background: transparent;
                border: none;
                border-radius: 0;
                outline: none;
                padding: 0;
            }
            TitleBar QPushButton:hover { background: #242424; }
            TitleBar QPushButton:pressed { background: #1a1a1a; }
            """
        )
        self._dragging = False
        self.logo = QLabel(self)
        self.logo.setPixmap(svg_icon("comet", "#f3f3f3", 18).pixmap(18, 18))
        self.app_label = QLabel(APP_SHORT_NAME, self)
        self.app_label.setStyleSheet("font-size: 13px; font-weight: 500; color: #f0f0f0;")
        self.title_label = QLabel("", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 500; color: #d8d8d8;")
        self.title_label.hide()
        self.min_button = self._window_button("minimize", "Minimize")
        self.max_button = self._window_button("maximize", "Maximize")
        self.close_button = self._window_button("close", "Close")
        self.close_button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 0; outline: none; padding: 0; } "
            "QPushButton:hover { background: #ff5f57; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(8)
        layout.addWidget(self.logo)
        layout.addWidget(self.app_label)
        layout.addStretch(1)
        layout.addWidget(self.title_label, 4)
        layout.addStretch(1)
        layout.addWidget(self.min_button)
        layout.addWidget(self.max_button)
        layout.addWidget(self.close_button)
        self.min_button.clicked.connect(self.minimizeClicked.emit)
        self.max_button.clicked.connect(self.maximizeClicked.emit)
        self.close_button.clicked.connect(self.closeClicked.emit)
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.opacity.setOpacity(1.0)
        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)

    def set_title(self, title: str) -> None:
        """Set currently playing title."""
        self.title_label.setText("")
        self.title_label.hide()

    def fade_to(self, opacity: float, duration: int) -> None:
        self.fade.stop()
        self.fade.setDuration(duration)
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(opacity)
        self.fade.start()

    def set_maximized(self, maximized: bool) -> None:
        """Update maximize icon."""
        self.max_button.setIcon(svg_icon("restore" if maximized else "maximize"))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximizeClicked.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.dragStarted.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self.dragMoved.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _window_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton(self)
        button.setFixedSize(42, 32)
        button.setIcon(svg_icon(icon_name))
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button
