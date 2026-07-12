"""Right-side playlist panel."""

from __future__ import annotations

from PyQt6.QtCore import QFile, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget

from core.playlist_manager import PlaylistItem
from ui.quick_settings import QuickSettingsPanel


class PlaylistPanel(QWidget):
    """Overlay playlist panel with selectable items."""

    itemActivated = pyqtSignal(int)
    removeRequested = pyqtSignal(int)
    addRequested = pyqtSignal()
    chapterActivated = pyqtSignal(float)
    quickSettingChanged = pyqtSignal(str, object)
    moveRequested = pyqtSignal(int, int)
    sortRequested = pyqtSignal(str)
    playNextRequested = pyqtSignal(int)

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
        self.tabs = QTabWidget(self)
        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        # Episode names can be very long.  A native horizontal scrollbar was
        # appearing as a striped/fragmented control at the panel footer; keep
        # rows single-line and elide them within the available width instead.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(True)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        playlist_page = QWidget(); playlist_layout = QVBoxLayout(playlist_page); playlist_layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout(); add = QPushButton("+"); self.sort = QComboBox(); self.sort.addItems(["Filename ↑", "Filename ↓", "Full path ↑", "Full path ↓"]); tools.addWidget(add); tools.addWidget(self.sort); tools.addStretch()
        self.footer = QLabel("0 items • 00:00")
        playlist_layout.addLayout(tools); playlist_layout.addWidget(self.list); playlist_layout.addWidget(self.footer)
        self.chapters = QListWidget(); self.chapters.itemDoubleClicked.connect(lambda item: self.chapterActivated.emit(float(item.data(Qt.ItemDataRole.UserRole) or 0)))
        quick = QuickSettingsPanel(); quick.propertyChanged.connect(self.quickSettingChanged.emit)
        self.tabs.addTab(playlist_page, "Playlist"); self.tabs.addTab(self.chapters, "Chapters"); self.tabs.addTab(quick, "Quick Settings")
        self.quick_settings = quick
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.tabs)
        self.list.itemDoubleClicked.connect(lambda item: self.itemActivated.emit(self.list.row(item)))
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.model().rowsMoved.connect(lambda _p, start, _end, _d, target: self.moveRequested.emit(start, target - 1 if target > start else target))
        add.clicked.connect(self.addRequested.emit)
        self.sort.currentTextChanged.connect(self.sortRequested.emit)

    def refresh(self, items: list[PlaylistItem], current_index: int) -> None:
        """Refresh items."""
        self.list.blockSignals(True)
        self.list.clear()
        for item in items:
            row = QListWidgetItem(item.title); row.setData(Qt.ItemDataRole.UserRole, item.source); self.list.addItem(row)
        if 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)
        self.footer.setText(f"{len(items)} items")
        self.list.blockSignals(False)

    def _context_menu(self, point: object) -> None:
        item = self.list.itemAt(point)
        if item is None: return
        index = self.list.row(item); source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        menu = QMenu(self); play = menu.addAction("Play Now"); play_next = menu.addAction("Play Next"); menu.addSeparator(); remove = menu.addAction("Remove"); delete = menu.addAction("Delete File…"); reveal = menu.addAction("Show in File Explorer"); copy = menu.addAction("Copy path / URL")
        selected = menu.exec(self.list.mapToGlobal(point))
        if selected is play: self.itemActivated.emit(index)
        elif selected is play_next: self.playNextRequested.emit(index)
        elif selected is remove: self.removeRequested.emit(index)
        elif selected is copy: QApplication.clipboard().setText(source)
        elif selected is reveal and source: __import__('subprocess').Popen(["explorer", "/select,", source])
        elif selected is delete and source and QMessageBox.question(self, "Delete file", f"Move {source} to the Recycle Bin?") == QMessageBox.StandardButton.Yes: QFile.moveToTrash(source); self.removeRequested.emit(index)

    def set_chapters(self, chapters: list[dict]) -> None:
        self.chapters.clear()
        for index, chapter in enumerate(chapters):
            title = chapter.get("title") or f"Chapter {index + 1}"
            start = float(chapter.get("time", chapter.get("start_time", 0)) or 0)
            item = QListWidgetItem(f"{title}  •  {int(start)//60:02d}:{int(start)%60:02d}")
            item.setData(Qt.ItemDataRole.UserRole, start); self.chapters.addItem(item)

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Delete and self.list.currentRow() >= 0:
            self.removeRequested.emit(self.list.currentRow())
            return
        super().keyPressEvent(event)
