"""Right-side playlist panel."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from core.playlist_manager import PlaylistItem


class PlaylistPanel(QWidget):
    """Overlay playlist panel with selectable items."""

    itemActivated = pyqtSignal(int)
    removeRequested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        # A tool window is required here: mpv renders into its own native HWND,
        # which can cover ordinary Qt child widgets regardless of raise_().
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setWindowTitle("Playlist")
        # Top-level styled widgets do not reliably fill their native backing
        # surface on Windows.  An explicit opaque palette prevents mpv and the
        # control bar from bleeding through unpainted parts of the panel.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0c0e12"))
        self.setPalette(palette)
        self.setStyleSheet(
            """
            PlaylistPanel { background: #0c0e12; border-left: 1px solid #292b30; }
            QListWidget { background: transparent; border: none; color: #f0f0f0; outline: none; }
            QListWidget::item { padding: 8px 10px; border-radius: 6px; }
            QListWidget::item:selected { background: #263a59; }
            """
        )
        self.list = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.list)
        self.list.itemDoubleClicked.connect(lambda item: self.itemActivated.emit(self.list.row(item)))

    def refresh(self, items: list[PlaylistItem], current_index: int) -> None:
        """Refresh items."""
        self.list.blockSignals(True)
        self.list.clear()
        for item in items:
            self.list.addItem(QListWidgetItem(item.title))
        if 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)
        self.list.blockSignals(False)

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Delete and self.list.currentRow() >= 0:
            self.removeRequested.emit(self.list.currentRow())
            return
        super().keyPressEvent(event)
