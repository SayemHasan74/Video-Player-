"""Right-side playlist panel."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QFile, QPoint, QSize, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPalette, QResizeEvent
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLayout, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from core.playlist_manager import PlaylistItem
from core.media_probe import matching_subtitles, probe_media
from ui.quick_settings import QuickSettingsPanel
from utils.time_utils import format_time


class PlaylistProbeWorker(QThread):
    probed = pyqtSignal(str, dict)
    def __init__(self, sources: list[str], parent: object | None = None) -> None: super().__init__(parent); self.sources=sources
    def run(self) -> None:
        for source in self.sources:
            if self.isInterruptionRequested(): return
            data=probe_media(source); fmt=data.get("format",{}); tags=fmt.get("tags",{}) or {}
            self.probed.emit(source,{"duration":float(fmt.get("duration") or 0),"title":tags.get("title") or Path(source).name,"artist":tags.get("artist") or "","album":tags.get("album") or "","subtitle":bool(matching_subtitles(source))})

class PlaylistListWidget(QListWidget):
    keyPressed = pyqtSignal(object)
    def event(self,event:object)->bool:
        if event.type()==QEvent.Type.ShortcutOverride:
            event.accept();return True
        return super().event(event)
    def keyPressEvent(self,event:object)->None:
        self.keyPressed.emit(event); event.accept()


class PlaylistRow(QWidget):
    clicked = pyqtSignal()

    def __init__(self, item: PlaylistItem, progress: float = 0) -> None:
        super().__init__(); self.setMinimumHeight(52); self.setMouseTracking(True); self.setCursor(Qt.CursorShape.ArrowCursor); self.source=item.source; self.title=ElidedLabel(item.title); self.title.setMinimumWidth(0); self.title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred); self.title.setStyleSheet("color:#f2f2f2;"); self.info=ElidedLabel(); self.info.setMinimumWidth(0); self.info.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred); self.info.setStyleSheet("color:#999; font-size:11px;"); self.duration=QLabel(format_time(item.duration) if item.duration else "--:--"); self.duration.setStyleSheet("font-family:Consolas; color:#bbb;"); self.subtitle=QLabel("CC" if item.has_subtitle else ""); self.subtitle.setStyleSheet("color:#8ab4ff;font-size:10px;font-weight:700;")
        top=QHBoxLayout(); top.setContentsMargins(0,0,0,0); top.addWidget(self.title,1); top.addWidget(self.subtitle); top.addWidget(self.duration)
        self.progress=QProgressBar(); self.progress.setRange(0,1000); self.progress.setValue(round(progress*1000)); self.progress.setTextVisible(False); self.progress.setFixedHeight(3); self.progress.setStyleSheet("QProgressBar{border:0;background:transparent}QProgressBar::chunk{border-radius:1px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(255,255,255,0),stop:.35 rgba(255,255,255,110),stop:.8 rgba(220,235,255,210),stop:1 rgba(255,255,255,0))}"); self.progress.setVisible(progress>0)
        layout=QVBoxLayout(self); layout.setContentsMargins(8,5,8,5); layout.setSpacing(2); layout.addLayout(top); layout.addWidget(self.info); layout.addWidget(self.progress); self.update_item(item)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def update_item(self,item:PlaylistItem)->None:
        self.title.set_full_text(item.title); self.info.set_full_text(" • ".join(value for value in (item.artist,item.album) if value)); self.info.setVisible(bool(self.info.full_text)); self.duration.setText(format_time(item.duration) if item.duration else "--:--"); self.subtitle.setText("CC" if item.has_subtitle else "")

class ElidedLabel(QLabel):
    def __init__(self,text:str="",parent:QWidget|None=None)->None:
        super().__init__(parent);self.full_text="";self.set_full_text(text)
    def set_full_text(self,text:str)->None:
        self.full_text=text;self._update_elision()
    def resizeEvent(self,event:QResizeEvent)->None:
        super().resizeEvent(event);self._update_elision()
    def _update_elision(self)->None:
        self.setText(self.fontMetrics().elidedText(self.full_text,Qt.TextElideMode.ElideRight,max(0,self.width())))


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
    widthChanged = pyqtSignal(int)
    tabChanged = pyqtSignal(str)
    keyPressed = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        # The render-context video surface participates in Qt composition, so
        # the playlist is a normal child overlay rather than another OS window.
        super().__init__(parent)
        self._side = "right"
        self._resizing = False
        self._resize_start = QPoint()
        self._resize_width = 320
        self._probe_worker: PlaylistProbeWorker | None = None
        self._probe_signature: tuple[str,...] = ()
        self._history: dict[str, tuple[float,float]] = {}
        self._items_by_source: dict[str, PlaylistItem] = {}
        self._row_sources: tuple[str, ...] = ()
        self.setMinimumWidth(240)
        self.setMaximumWidth(600)
        self.setMouseTracking(True)
        # Keep the panel opaque above the video while remaining in one Qt tree.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0c0e12"))
        self.setPalette(palette)
        self.setStyleSheet(
            """
            PlaylistPanel { background: #0c0e12; border-left: 1px solid #292b30; }
            QTabWidget::pane { border: none; background: #0c0e12; }
            QTabBar::tab { background: #0c0e12; color: #aeb3bb; padding: 8px 10px; border: none; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #5e9bff; }
            QTabBar::tab:hover { background: #181b20; color: white; }
            QListWidget { background: transparent; border: none; color: #f0f0f0; outline: none; }
            QListWidget::item { padding: 0; margin: 1px 0; border-radius: 6px; }
            QListWidget::item:selected { background: transparent; }
            QListWidget::item:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(255,255,255,5),stop:.5 rgba(255,255,255,22),stop:1 rgba(255,255,255,5)); }
            QPushButton { background: #17191d; color: #e8e8e8; border: 1px solid #292c32; border-radius: 5px; padding: 5px 9px; }
            QPushButton:hover { background: #242831; border-color: #3b414c; }
            QPushButton:pressed { background: #101216; padding-top: 6px; padding-bottom: 4px; }
            QComboBox { background: #15171b; color: #eeeeee; border: 1px solid #292c32; border-radius: 5px; padding: 5px 8px; }
            QComboBox::drop-down { border: none; width: 20px; }
            QScrollBar:vertical { background: #0c0e12; width: 9px; margin: 0; }
            QScrollBar::handle:vertical { background: #343942; min-height: 30px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #4a515d; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: none; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            """
        )
        self.tabs = QTabWidget(self)
        self.list = PlaylistListWidget(self)
        self.list.setCursor(Qt.CursorShape.ArrowCursor)
        self.list.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.list.keyPressed.connect(self._list_key_pressed)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        # Episode names can be very long.  A native horizontal scrollbar was
        # appearing as a striped/fragmented control at the panel footer; keep
        # rows single-line and elide them within the available width instead.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(False)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        playlist_page = QWidget(); playlist_layout = QVBoxLayout(playlist_page); playlist_layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout(); add = QPushButton("+"); self.sort = QComboBox(); self.sort.addItems(["Filename ↑", "Filename ↓", "Full path ↑", "Full path ↓"]); tools.addWidget(add); tools.addWidget(self.sort); tools.addStretch()
        self.footer = QLabel("0 items • 00:00")
        playlist_layout.addLayout(tools); playlist_layout.addWidget(self.list); playlist_layout.addWidget(self.footer)
        self.chapters = QListWidget(); self.chapters.itemDoubleClicked.connect(lambda item: self.chapterActivated.emit(float(item.data(Qt.ItemDataRole.UserRole) or 0)))
        quick = QuickSettingsPanel(); quick.propertyChanged.connect(self.quickSettingChanged.emit)
        self.tabs.addTab(playlist_page, "Playlist"); self.tabs.addTab(self.chapters, "Chapters"); self.tabs.addTab(quick, "Quick Settings")
        self.quick_settings = quick
        self.tabs.currentChanged.connect(lambda index: self.tabChanged.emit(("playlist", "chapters", "quick_settings")[max(0, min(index, 2))]))
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.tabs)
        self.list.itemClicked.connect(self._item_clicked)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.model().rowsMoved.connect(lambda _p, start, _end, _d, target: self.moveRequested.emit(start, target - 1 if target > start else target))
        add.clicked.connect(self.addRequested.emit)
        self.sort.currentTextChanged.connect(self.sortRequested.emit)

    def _item_clicked(self, item: QListWidgetItem) -> None:
        """Play immediately on a normal click; modifiers remain selection-only."""
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        self.itemActivated.emit(self.list.row(item))

    def _row_clicked(self, source: str) -> None:
        """Activate an item-widget row, which otherwise sits above the list viewport."""
        if QApplication.keyboardModifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == source:
                self.list.setCurrentRow(index)
                self.itemActivated.emit(index)
                return

    def set_side(self, side: str) -> None:
        self._side = "left" if side == "left" else "right"

    def set_current_tab(self, name: str) -> None:
        index = {"playlist": 0, "chapters": 1, "quick_settings": 2}.get(name, 0)
        self.tabs.setCurrentIndex(index)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        edge = event.position().x() >= self.width() - 4 if self._side == "left" else event.position().x() <= 4
        if event.button() == Qt.MouseButton.LeftButton and edge:
            self._resizing = True; self._resize_start = event.globalPosition().toPoint(); self._resize_width = self.width(); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start.x()
            width = self._resize_width + delta if self._side == "left" else self._resize_width - delta
            self.widthChanged.emit(max(240, min(600, width))); event.accept(); return
        edge = event.position().x() >= self.width() - 4 if self._side == "left" else event.position().x() <= 4
        self.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            self._resizing = False; self.unsetCursor(); event.accept(); return
        super().mouseReleaseEvent(event)

    def refresh(self, items: list[PlaylistItem], current_index: int, history: dict[str, tuple[float,float]] | None = None) -> None:
        """Refresh items."""
        signature=tuple(item.source for item in items)
        if signature == self._row_sources and self.list.count()==len(items):
            self.list.blockSignals(True)
            self.list.setCurrentRow(current_index if 0<=current_index<len(items) else -1)
            self.list.blockSignals(False)
            return
        self.list.blockSignals(True)
        self.list.clear()
        self._row_sources=signature
        self._history = history or self._history
        self._items_by_source = {item.source: item for item in items}
        for item in items:
            position,total=self._history.get(item.source,(0,0)); progress=position/total if total else 0
            widget=PlaylistRow(item,progress); widget.clicked.connect(lambda source=item.source: self._row_clicked(source)); row = QListWidgetItem(); row.setData(Qt.ItemDataRole.UserRole, item.source); row.setSizeHint(QSize(0,54)); self.list.addItem(row); self.list.setItemWidget(row,widget)
        if 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)
        total=sum(item.duration for item in items); self.footer.setText(f"{len(items)} items • {format_time(total)}")
        self.list.blockSignals(False)
        probe_signature=tuple(item.source for item in items if not item.is_url)
        if probe_signature != self._probe_signature:
            self._probe_signature=probe_signature
            if self._probe_worker and self._probe_worker.isRunning(): self._probe_worker.requestInterruption()
            self._probe_worker=PlaylistProbeWorker(list(probe_signature),self); self._probe_worker.probed.connect(self._metadata_ready); self._probe_worker.start()

    def _metadata_ready(self, source: str, metadata: dict) -> None:
        model_item=self._items_by_source.get(source)
        if model_item:
            model_item.title=metadata["title"]; model_item.duration=metadata["duration"]; model_item.artist=metadata["artist"]; model_item.album=metadata["album"]; model_item.has_subtitle=metadata["subtitle"]
        for row in range(self.list.count()):
            list_item=self.list.item(row)
            if list_item.data(Qt.ItemDataRole.UserRole)==source:
                widget=self.list.itemWidget(list_item); item=PlaylistItem(source,metadata["title"],False,metadata["duration"],metadata["artist"],metadata["album"],metadata["subtitle"]); widget.update_item(item); list_item.setSizeHint(QSize(0,54)); break
        total=sum(item.duration for item in self._items_by_source.values())
        self.footer.setText(f"{self.list.count()} items • {format_time(total)}")

    def update_progress(self, source: str, position: float, duration: float) -> None:
        for row in range(self.list.count()):
            item=self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole)==source:
                widget=self.list.itemWidget(item); value=round(1000*position/duration) if duration else 0; widget.progress.setValue(value); widget.progress.setVisible(value>0); break

    def shutdown(self) -> None:
        if self._probe_worker and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption(); self._probe_worker.wait(2000)

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
        self.keyPressed.emit(event)
        event.accept()

    def _list_key_pressed(self,event:object)->None:
        if event.key()==Qt.Key.Key_Delete and self.list.currentRow()>=0:self.removeRequested.emit(self.list.currentRow())
        else:self.keyPressed.emit(event)
