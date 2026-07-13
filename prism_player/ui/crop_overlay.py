"""Interactive crop rectangle drawn inside the Qt video surface."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class CropSelectionOverlay(QWidget):
    selectionFinished = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._start = QPoint()
        self._selection = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

    def begin(self) -> None:
        self._selection = QRect()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect(self._start, self._start)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._selection = QRect(self._start, event.position().toPoint()).normalized().intersected(self.rect())
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            selection = self._selection.normalized().intersected(self.rect())
            self.hide()
            if selection.width() >= 8 and selection.height() >= 8:
                self.selectionFinished.emit(selection)
            else:
                self.cancelled.emit()
            event.accept()

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._selection.isValid():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._selection, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#f2f2f2"), 2))
            painter.drawRect(self._selection.adjusted(1, 1, -1, -1))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(self._selection.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignTop, f"{self._selection.width()} × {self._selection.height()}")
