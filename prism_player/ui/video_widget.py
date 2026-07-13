"""mpv render target and user input surface."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QWidget


class VideoWidget(QWidget):
    """Black video surface that emits high-level input signals."""

    doubleClicked = pyqtSignal()
    clicked = pyqtSignal()
    rightClicked = pyqtSignal(QPoint)
    middleClicked = pyqtSignal()
    scrolled = pyqtSignal(int)
    mouseMoved = pyqtSignal()
    mousePositionChanged = pyqtSignal(QPoint)
    keyPressed = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse button actions."""
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Toggle play/pause on double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Notify that controls may need to reappear."""
        self.mousePositionChanged.emit(event.position().toPoint())
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Emit wheel volume changes."""
        self.scrolled.emit(5 if event.angleDelta().y() > 0 else -5)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Forward key events to the controller."""
        self.keyPressed.emit(event)
        event.accept()
