"""Right-side playlist panel."""

from __future__ import annotations

import os
from threading import Lock
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QEvent, QFile, QPoint, QRect, QSize, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QLinearGradient, QMouseEvent, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLayout, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTabWidget, QToolButton, QVBoxLayout, QWidget

from core.playlist_manager import PlaylistItem
from core.media_probe import matching_subtitles, probe_media
from ui.quick_settings import QuickSettingsPanel
from utils.time_utils import format_time


_PROBE_CACHE: dict[tuple[object, ...], dict] = {}
_PROBE_CACHE_LOCK = Lock()
_PROBE_CACHE_LIMIT = 2048


class PlaylistProbeWorker(QThread):
    probed = pyqtSignal(str, dict)
    def __init__(self, sources: list[tuple[str, bool, set[str]]], parent: object | None = None) -> None: super().__init__(parent); self.sources=sources
    def run(self) -> None:
        for source, autoload_subtitles, wrong_subtitles in self.sources:
            if self.isInterruptionRequested(): return
            path = Path(source)
            try:
                stat = path.stat()
                fingerprint = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                fingerprint = (0, 0)
            cache_key = (
                str(path.resolve()).casefold(), *fingerprint,
                autoload_subtitles, tuple(sorted(wrong_subtitles)),
            )
            with _PROBE_CACHE_LOCK:
                cached = _PROBE_CACHE.get(cache_key)
            if cached is not None:
                self.probed.emit(source, dict(cached))
                continue
            data=probe_media(source); fmt=data.get("format",{}); tags=fmt.get("tags",{}) or {}
            matches = [] if not autoload_subtitles else [path for path in matching_subtitles(source) if str(Path(path).resolve()).casefold() not in wrong_subtitles]
            metadata={"duration":float(fmt.get("duration") or 0),"title":tags.get("title") or Path(source).name,"artist":tags.get("artist") or "","album":tags.get("album") or "","subtitle":bool(matches)}
            with _PROBE_CACHE_LOCK:
                _PROBE_CACHE[cache_key] = dict(metadata)
                if len(_PROBE_CACHE) > _PROBE_CACHE_LIMIT:
                    _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)))
            self.probed.emit(source, metadata)

class PlaylistListWidget(QListWidget):
    keyPressed = pyqtSignal(object)
    def event(self,event:object)->bool:
        if event.type()==QEvent.Type.ShortcutOverride:
            event.accept();return True
        return super().event(event)
    def keyPressEvent(self,event:object)->None:
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.selectAll(); event.accept(); return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            super().keyPressEvent(event); return
        self.keyPressed.emit(event); event.accept()


class PlaylistItemDelegate(QStyledItemDelegate):
    """Paint compact rows without hundreds of child widgets during resize."""

    def __init__(self, panel: "PlaylistPanel") -> None:
        super().__init__(panel.list)
        self.panel = panel
        self.duration_font = QFont("Consolas")

    def sizeHint(self, option: QStyleOptionViewItem, index: object) -> QSize:
        return QSize(max(1, option.rect.width()), 54)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: object) -> None:
        source = str(index.data(Qt.ItemDataRole.UserRole) or "")
        item = self.panel._items_by_source.get(source)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(2, 1, -2, -1)
        if option.state & QStyle.StateFlag.State_MouseOver:
            hover = QLinearGradient(rect.left(), 0, rect.right(), 0)
            hover.setColorAt(0.0, QColor(255, 255, 255, 4))
            hover.setColorAt(0.5, QColor(255, 255, 255, 22))
            hover.setColorAt(1.0, QColor(255, 255, 255, 4))
            painter.fillRect(rect, hover)

        content = rect.adjusted(7, 4, -7, -4)
        duration = format_time(item.duration) if item.duration else "--:--"
        painter.setFont(self.duration_font)
        duration_width = painter.fontMetrics().horizontalAdvance(duration) + 4
        subtitle_text = "CC" if item.has_subtitle or item.subtitle_paths else ""
        subtitle_width = 22 if subtitle_text else 0

        title_font = option.font
        painter.setFont(title_font)
        title_right = content.right() - duration_width - subtitle_width - 8
        title_rect = QRect(content.left(), content.top(), max(1, title_right - content.left()), 22)
        title = painter.fontMetrics().elidedText(item.title, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.setPen(QColor("#f2f2f2"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

        if subtitle_text:
            subtitle_rect = QRect(title_right + 3, content.top(), subtitle_width, 22)
            subtitle_font = QFont(title_font); subtitle_font.setPointSize(max(7, title_font.pointSize() - 2)); subtitle_font.setBold(True)
            painter.setFont(subtitle_font); painter.setPen(QColor("#8ab4ff"))
            painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignCenter, subtitle_text)

        duration_rect = QRect(content.right() - duration_width, content.top(), duration_width, 22)
        painter.setFont(self.duration_font); painter.setPen(QColor("#bbbbbb"))
        painter.drawText(duration_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, duration)

        details = [value for value in (item.artist, item.album) if value]
        path_text = self.panel._display_path(item)
        if path_text:
            details.append(path_text)
        detail_text = " • ".join(details)
        if detail_text:
            detail_font = QFont(title_font); detail_font.setPointSize(max(7, title_font.pointSize() - 1))
            painter.setFont(detail_font); painter.setPen(QColor("#999999"))
            detail_rect = QRect(content.left(), content.top() + 23, content.width(), 18)
            detail_text = painter.fontMetrics().elidedText(detail_text, Qt.TextElideMode.ElideRight, detail_rect.width())
            painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, detail_text)

        position, total = self.panel._history.get(source, (0.0, 0.0))
        progress = max(0.0, min(1.0, position / total)) if total else 0.0
        if progress > 0:
            beam_width = max(2, round(content.width() * progress))
            beam_rect = QRect(content.left(), rect.bottom() - 3, beam_width, 3)
            beam = QLinearGradient(beam_rect.left(), 0, beam_rect.right(), 0)
            beam.setColorAt(0.0, QColor(255, 255, 255, 0))
            beam.setColorAt(0.35, QColor(255, 255, 255, 95))
            beam.setColorAt(0.8, QColor(220, 235, 255, 205))
            beam.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(beam_rect, beam)
        painter.restore()


class PlaylistPanel(QWidget):
    """Overlay playlist panel with selectable items."""

    itemActivated = pyqtSignal(int)
    removeRequested = pyqtSignal(int)
    removeManyRequested = pyqtSignal(list)
    addRequested = pyqtSignal()
    chapterActivated = pyqtSignal(float)
    quickSettingChanged = pyqtSignal(str, object)
    moveRequested = pyqtSignal(int, int)
    moveManyRequested = pyqtSignal(list, int)
    sortRequested = pyqtSignal(str)
    playNextRequested = pyqtSignal(int)
    widthChanged = pyqtSignal(int)
    tabChanged = pyqtSignal(str)
    keyPressed = pyqtSignal(object)
    metadataChanged = pyqtSignal(str, dict)
    playlistPinToggled = pyqtSignal(bool)
    quickPinToggled = pyqtSignal(bool)
    newWindowRequested = pyqtSignal(str)
    addSubtitleRequested = pyqtSignal(str, str)
    subtitleViewRequested = pyqtSignal(str, str)
    subtitleWrongRequested = pyqtSignal(str, str)
    repeatOneToggled = pyqtSignal(bool)
    repeatAllToggled = pyqtSignal(bool)
    shuffleToggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        # The render-context video surface participates in Qt composition, so
        # the playlist is a normal child overlay rather than another OS window.
        super().__init__(parent)
        self._side = "right"
        self._resizing = False
        self._resize_start = QPoint()
        self._resize_width = 320
        self._probe_worker: PlaylistProbeWorker | None = None
        self._probe_workers: set[PlaylistProbeWorker] = set()
        self._probe_signature: tuple[object,...] = ()
        self._history: dict[str, tuple[float,float]] = {}
        self._items_by_source: dict[str, PlaylistItem] = {}
        self._row_sources: tuple[str, ...] = ()
        self._plugin_tab_ids: set[str] = set()
        self._plugin_context_items: list[tuple[str, Callable[[int, str], None]]] = []
        self._requested_tab = "playlist"
        self._quick_settings_pinned = False
        self._common_prefix = ""
        self._show_full_paths = False
        self._chapters: list[dict] = []
        self.setMinimumWidth(240)
        self.setMaximumWidth(600)
        self.setMouseTracking(True)
        # A styled/autofilled background clears newly exposed pixels. Do not
        # claim WA_OpaquePaintEvent: transparent tab/list child regions do not
        # paint every pixel and would leave stale duplicated fragments behind.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0c0e12"))
        self.setPalette(palette)
        self.setStyleSheet(
            """
            PlaylistPanel { background: #0c0e12; border-left: 1px solid #292b30; }
            QTabWidget, QTabWidget::pane, QTabBar { border: none; background: #0c0e12; }
            QTabBar::tab { background: #0c0e12; color: #aeb3bb; padding: 8px 10px; border: none; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #5e9bff; }
            QTabBar::tab:hover { background: #181b20; color: white; }
            QListWidget, QListWidget::viewport { background: #0c0e12; border: none; color: #f0f0f0; outline: none; }
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
        self.list.setItemDelegate(PlaylistItemDelegate(self))
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
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
        self.list.setUniformItemSizes(True)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        playlist_page = QWidget(); playlist_layout = QVBoxLayout(playlist_page); playlist_layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout(); add = QPushButton("+"); self.sort = QComboBox(); self.sort.addItems(["Filename ↑", "Filename ↓", "Full path ↑", "Full path ↓"]); tools.addWidget(add); tools.addWidget(self.sort)
        self.path_prefix = QToolButton(); self.path_prefix.setCheckable(True); self.path_prefix.setText("Path ▸"); self.path_prefix.setToolTip("Show the common folder path"); self.path_prefix.hide(); tools.addWidget(self.path_prefix); tools.addStretch(1)
        self.repeat_one_button = QToolButton(); self.repeat_one_button.setText("Repeat 1"); self.repeat_one_button.setCheckable(True); self.repeat_one_button.setToolTip("Repeat the current item")
        self.repeat_all_button = QToolButton(); self.repeat_all_button.setText("Repeat All"); self.repeat_all_button.setCheckable(True); self.repeat_all_button.setToolTip("Repeat the playlist")
        self.shuffle_button = QToolButton(); self.shuffle_button.setText("Shuffle"); self.shuffle_button.setCheckable(True)
        mode_row = QHBoxLayout(); mode_row.addStretch(1)
        for button in (self.repeat_one_button, self.repeat_all_button, self.shuffle_button): mode_row.addWidget(button)
        self.footer = QLabel("0 items • 00:00")
        playlist_layout.addLayout(tools); playlist_layout.addLayout(mode_row); playlist_layout.addWidget(self.list); playlist_layout.addWidget(self.footer)
        self.chapters = QListWidget(); self.chapters.itemDoubleClicked.connect(lambda item: self.chapterActivated.emit(float(item.data(Qt.ItemDataRole.UserRole) or 0)))
        quick = QuickSettingsPanel(); quick.propertyChanged.connect(self.quickSettingChanged.emit)
        self.tabs.addTab(playlist_page, "Playlist"); self.tabs.addTab(self.chapters, "Chapters"); self.tabs.addTab(quick, "Quick Settings")
        for index, name in enumerate(("playlist", "chapters", "quick_settings")):
            self.tabs.tabBar().setTabData(index, name)
        self.quick_settings = quick
        self.tabs.currentChanged.connect(self._tab_changed)
        self.playlist_pin_button = QPushButton("Pin Playlist")
        self.playlist_pin_button.setCheckable(True)
        self.quick_pin_button = QPushButton("Pin Quick Settings ↔")
        self.quick_pin_button.setCheckable(True)
        pin_row = QHBoxLayout()
        pin_row.setContentsMargins(0, 0, 0, 0)
        pin_row.addWidget(self.playlist_pin_button)
        pin_row.addWidget(self.quick_pin_button)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(pin_row)
        layout.addWidget(self.tabs)
        self.list.itemClicked.connect(self._item_clicked)
        self.list.itemSelectionChanged.connect(self._update_footer)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.model().rowsMoved.connect(self._rows_moved)
        add.clicked.connect(self.addRequested.emit)
        self.sort.currentTextChanged.connect(self.sortRequested.emit)
        self.playlist_pin_button.toggled.connect(self.playlistPinToggled)
        self.quick_pin_button.toggled.connect(self.quickPinToggled)
        self.path_prefix.toggled.connect(self._path_visibility_changed)
        self.repeat_one_button.toggled.connect(self.repeatOneToggled)
        self.repeat_all_button.toggled.connect(self.repeatAllToggled)
        self.shuffle_button.toggled.connect(self.shuffleToggled)

    def _item_clicked(self, item: QListWidgetItem) -> None:
        """Play immediately on a normal click; modifiers remain selection-only."""
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        self.itemActivated.emit(self.list.row(item))

    def _rows_moved(self, _parent: object, start: int, end: int, _destination: object, target: int) -> None:
        indices = list(range(start, end + 1))
        if len(indices) == 1:
            self.moveRequested.emit(start, target - 1 if target > start else target)
        else:
            self.moveManyRequested.emit(indices, target)

    def set_side(self, side: str) -> None:
        self._side = "left" if side == "left" else "right"

    def set_current_tab(self, name: str) -> None:
        self._requested_tab = name
        for index in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(index) == name:
                self.tabs.setCurrentIndex(index)
                return
        self.tabs.setCurrentIndex(0)

    def _tab_changed(self, index: int) -> None:
        name = self.tabs.tabBar().tabData(index) if index >= 0 else "playlist"
        self._requested_tab = str(name or "playlist")
        self.tabChanged.emit(str(name or "playlist"))

    def set_playlist_pinned(self, pinned: bool) -> None:
        self.playlist_pin_button.blockSignals(True)
        self.playlist_pin_button.setChecked(bool(pinned))
        self.playlist_pin_button.setText("Unpin Playlist" if pinned else "Pin Playlist")
        self.playlist_pin_button.blockSignals(False)

    def detach_quick_settings(self) -> QuickSettingsPanel:
        if self._quick_settings_pinned:
            return self.quick_settings
        for index in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(index) == "quick_settings":
                self.tabs.blockSignals(True)
                self.tabs.removeTab(index)
                self.tabs.blockSignals(False)
                break
        self._quick_settings_pinned = True
        self.quick_pin_button.blockSignals(True)
        self.quick_pin_button.setChecked(True)
        self.quick_pin_button.setText("Unpin Quick Settings")
        self.quick_pin_button.blockSignals(False)
        return self.quick_settings

    def attach_quick_settings(self) -> None:
        if not self._quick_settings_pinned:
            return
        self._quick_settings_pinned = False
        index = min(2, self.tabs.count())
        self.tabs.blockSignals(True)
        self.tabs.insertTab(index, self.quick_settings, "Quick Settings")
        self.tabs.tabBar().setTabData(index, "quick_settings")
        self.tabs.blockSignals(False)
        self.quick_pin_button.blockSignals(True)
        self.quick_pin_button.setChecked(False)
        self.quick_pin_button.setText("Pin Quick Settings ↔")
        self.quick_pin_button.blockSignals(False)
        self.set_current_tab(self._requested_tab)

    def add_plugin_tab(self, tab_id: str, title: str, widget: QWidget) -> None:
        key = f"plugin:{tab_id}"
        self.remove_plugin_tab(tab_id)
        index = self.tabs.addTab(widget, title)
        self.tabs.tabBar().setTabData(index, key)
        self._plugin_tab_ids.add(tab_id)

    def remove_plugin_tab(self, tab_id: str) -> None:
        key = f"plugin:{tab_id}"
        for index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.tabBar().tabData(index) == key:
                widget = self.tabs.widget(index)
                self.tabs.removeTab(index)
                widget.deleteLater()
        self._plugin_tab_ids.discard(tab_id)

    def clear_plugin_tabs(self) -> None:
        for tab_id in tuple(self._plugin_tab_ids):
            self.remove_plugin_tab(tab_id)

    def set_plugin_context_items(self, items: list[tuple[str, Callable[[int, str], None]]]) -> None:
        self._plugin_context_items = list(items)

    def set_playback_modes(self, repeat_one: bool, repeat_all: bool, shuffle: bool) -> None:
        for button, value in (
            (self.repeat_one_button, repeat_one),
            (self.repeat_all_button, repeat_all),
            (self.shuffle_button, shuffle),
        ):
            button.blockSignals(True)
            button.setChecked(bool(value))
            button.blockSignals(False)

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
            self._items_by_source = {item.source: item for item in items}
            self.list.blockSignals(True)
            self.list.setCurrentRow(current_index if 0<=current_index<len(items) else -1)
            self.list.blockSignals(False)
            self.list.viewport().update()
            self._update_footer()
            self._ensure_probe(items)
            return
        self.list.blockSignals(True)
        self.list.clear()
        self._row_sources=signature
        self._history = history or self._history
        self._items_by_source = {item.source: item for item in items}
        self._common_prefix = self._find_common_prefix(items)
        self.path_prefix.setVisible(bool(self._common_prefix))
        if self._common_prefix:
            self._update_path_toggle()
        for item in items:
            row = QListWidgetItem(); row.setData(Qt.ItemDataRole.UserRole, item.source); row.setSizeHint(QSize(0,54)); self.list.addItem(row)
        if 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)
        self.list.blockSignals(False)
        self._update_footer()
        self._ensure_probe(items)

    def _ensure_probe(self, items: list[PlaylistItem]) -> None:
        probe_signature=tuple((item.source, item.autoload_subtitles, frozenset(item.wrong_subtitles)) for item in items if not item.is_url)
        if probe_signature != self._probe_signature:
            self._probe_signature=probe_signature
            if self._probe_worker and self._probe_worker.isRunning(): self._probe_worker.requestInterruption()
            worker=PlaylistProbeWorker([(source, autoload, set(wrong)) for source, autoload, wrong in probe_signature],self)
            self._probe_worker=worker
            self._probe_workers.add(worker)
            worker.probed.connect(self._metadata_ready)
            worker.finished.connect(lambda worker=worker: self._probe_finished(worker))
            worker.start()

    def _probe_finished(self, worker: PlaylistProbeWorker) -> None:
        self._probe_workers.discard(worker)
        if self._probe_worker is worker:
            self._probe_worker = None
        worker.deleteLater()

    def _metadata_ready(self, source: str, metadata: dict) -> None:
        model_item=self._items_by_source.get(source)
        if model_item is None:
            return
        if not model_item.title_explicit: model_item.title=metadata["title"]
        model_item.duration=metadata["duration"]; model_item.artist=metadata["artist"]; model_item.album=metadata["album"]; model_item.has_subtitle=metadata["subtitle"]
        for row in range(self.list.count()):
            list_item=self.list.item(row)
            if list_item.data(Qt.ItemDataRole.UserRole)==source:
                self.list.viewport().update(self.list.visualItemRect(list_item)); break
        self._update_footer()
        self.metadataChanged.emit(source, dict(metadata))

    def _find_common_prefix(self, items: list[PlaylistItem]) -> str:
        local = [str(Path(item.source).resolve().parent) for item in items if not item.is_url]
        if len(local) < 2 or any(len(Path(item.source).name) < 12 for item in items):
            return ""
        try:
            prefix = os.path.commonpath(local)
        except ValueError:
            return ""
        return prefix if len(prefix) >= 7 else ""

    def _display_path(self, item: PlaylistItem) -> str:
        if item.is_url:
            return item.source
        path = Path(item.source)
        if not self._common_prefix or self._show_full_paths:
            return str(path.parent)
        try:
            relative_parent = path.parent.relative_to(self._common_prefix)
        except ValueError:
            return str(path.parent)
        text = str(relative_parent)
        return "" if text == "." else f"…/{text}"

    def _path_visibility_changed(self, checked: bool) -> None:
        self._show_full_paths = bool(checked)
        self._update_path_toggle()
        for row in range(self.list.count()):
            list_item = self.list.item(row)
            self.list.viewport().update(self.list.visualItemRect(list_item))

    def _update_path_toggle(self) -> None:
        self.path_prefix.setText("Path ▾" if self._show_full_paths else "Path ▸")
        action = "Hide" if self._show_full_paths else "Show"
        self.path_prefix.setToolTip(f"{action} common folder: {self._common_prefix}")

    def _selected_indices(self, fallback: int | None = None) -> list[int]:
        indices = sorted({self.list.row(item) for item in self.list.selectedItems()})
        if fallback is not None and fallback not in indices:
            self.list.setCurrentRow(fallback)
            indices = [fallback]
        return indices

    def _update_footer(self) -> None:
        total = sum(item.duration for item in self._items_by_source.values())
        selected_indices = self._selected_indices()
        selected_duration = sum(
            self._items_by_source.get(str(self.list.item(index).data(Qt.ItemDataRole.UserRole) or ""), PlaylistItem("", "")).duration
            for index in selected_indices
        )
        text = f"{self.list.count()} items • {format_time(total)}"
        if selected_indices:
            text += f"  |  selected {len(selected_indices)} • {format_time(selected_duration)}"
        self.footer.setText(text)

    def update_progress(self, source: str, position: float, duration: float) -> None:
        self._history[source] = (float(position), float(duration))
        for row in range(self.list.count()):
            item=self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole)==source:
                self.list.viewport().update(self.list.visualItemRect(item)); break

    def shutdown(self) -> None:
        workers = tuple(self._probe_workers)
        for worker in workers:
            if worker.isRunning():
                worker.requestInterruption()
        for worker in workers:
            if worker.isRunning() and not worker.wait(3000):
                # probe_media has its own timeout; this is only a last-resort
                # shutdown guard against Qt destroying a live QThread.
                worker.terminate()
                worker.wait()
        self._probe_workers.clear()
        self._probe_worker = None

    def _context_menu(self, point: object) -> None:
        item = self.list.itemAt(point)
        if item is None:
            return
        index = self.list.row(item)
        indices = self._selected_indices(index)
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        menu, handlers = self._build_context_menu(index, indices, source)
        selected = menu.exec(self.list.mapToGlobal(point))
        handler = handlers.get(selected)
        if handler is not None:
            handler()

    def _build_context_menu(self, index: int, indices: list[int], source: str) -> tuple[QMenu, dict[object, Callable[[], None]]]:
        """Build the row menu separately so action enablement is regression-testable."""
        menu = QMenu(self)
        handlers: dict[object, Callable[[], None]] = {}

        def action(title: str, callback: Callable[[], None], enabled: bool = True) -> object:
            created = menu.addAction(title)
            created.setEnabled(enabled)
            handlers[created] = callback
            return created

        action("Play Now", lambda: self.itemActivated.emit(index))
        action("Play Next", lambda: self.playNextRequested.emit(index))
        action("Play in New Window", lambda: self.newWindowRequested.emit(source))
        move_menu = menu.addMenu("Move Selected")
        move_top = move_menu.addAction("To Top")
        move_bottom = move_menu.addAction("To Bottom")
        handlers[move_top] = lambda: self.moveManyRequested.emit(indices, 0)
        handlers[move_bottom] = lambda: self.moveManyRequested.emit(indices, self.list.count())
        menu.addSeparator()
        action("Remove Selected", lambda: self.removeManyRequested.emit(indices))

        local_sources = [
            str(self.list.item(row).data(Qt.ItemDataRole.UserRole) or "") for row in indices
        ]
        all_local = bool(local_sources) and all(
            source_text and not self._items_by_source.get(source_text, PlaylistItem(source_text, "", True)).is_url
            and Path(source_text).is_file()
            for source_text in local_sources
        )
        action("Delete Local File(s)…", lambda: self._delete_local_files(indices, local_sources), all_local)
        action("Show in File Explorer", lambda: __import__('subprocess').Popen(["explorer", "/select,", source]), all_local and len(indices) == 1)
        action("Copy path / URL", lambda: QApplication.clipboard().setText("\n".join(local_sources)))

        menu.addSeparator()
        add_subtitle = action("Add Subtitle File…", lambda: self._choose_subtitle(source), all_local and len(indices) == 1)
        _ = add_subtitle
        model = self._items_by_source.get(source)
        matched = []
        if model is not None and not model.is_url and model.autoload_subtitles:
            matched = [
                str(path) for path in matching_subtitles(source)
                if str(Path(path).resolve()).casefold() not in model.wrong_subtitles
            ]
        if model is not None:
            matched.extend(path for path in model.subtitle_paths if path not in matched)
        matched_menu = menu.addMenu("Matched Subtitles")
        matched_menu.setEnabled(bool(matched))
        for subtitle in matched:
            view = matched_menu.addAction(f"View: {Path(subtitle).name}")
            wrong = matched_menu.addAction(f"Wrong Match: {Path(subtitle).name}")
            handlers[view] = lambda subtitle=subtitle: self.subtitleViewRequested.emit(source, subtitle)
            handlers[wrong] = lambda subtitle=subtitle: self.subtitleWrongRequested.emit(source, subtitle)

        if self._plugin_context_items:
            menu.addSeparator()
            for title, callback in self._plugin_context_items:
                plugin = menu.addAction(title)
                handlers[plugin] = lambda callback=callback: callback(index, source)
        return menu, handlers

    def _choose_subtitle(self, source: str) -> None:
        subtitle, _ = QFileDialog.getOpenFileName(
            self, "Add Subtitle", str(Path(source).parent), "Subtitles (*.srt *.ass *.ssa *.sub *.vtt);;All files (*)"
        )
        if subtitle:
            self.addSubtitleRequested.emit(source, subtitle)

    def _delete_local_files(self, indices: list[int], sources: list[str]) -> None:
        names = "\n".join(Path(source).name for source in sources)
        if QMessageBox.question(self, "Delete local files", f"Move these files to the Recycle Bin?\n\n{names}") != QMessageBox.StandardButton.Yes:
            return
        removed: list[int] = []
        for index, source in zip(indices, sources):
            if QFile.moveToTrash(source):
                removed.append(index)
        if removed:
            self.removeManyRequested.emit(removed)

    def set_chapters(self, chapters: list[dict]) -> None:
        self._chapters = list(chapters)
        self.chapters.clear()
        for index, chapter in enumerate(chapters):
            title = chapter.get("title") or f"Chapter {index + 1}"
            start = float(chapter.get("time", chapter.get("start_time", 0)) or 0)
            item = QListWidgetItem(f"{title}  •  {int(start)//60:02d}:{int(start)%60:02d}")
            item.setData(Qt.ItemDataRole.UserRole, start); self.chapters.addItem(item)

    def update_current_chapter(self, position: float) -> None:
        current = -1
        for index in range(self.chapters.count()):
            start = float(self.chapters.item(index).data(Qt.ItemDataRole.UserRole) or 0)
            if start <= position:
                current = index
            else:
                break
        for index in range(self.chapters.count()):
            item = self.chapters.item(index)
            active = index == current
            item.setBackground(QColor("#263a59") if active else QColor(Qt.GlobalColor.transparent))
            font = item.font(); font.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Normal); item.setFont(font)

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Delete and self.list.currentRow() >= 0:
            self.removeManyRequested.emit(self._selected_indices(self.list.currentRow()))
            return
        self.keyPressed.emit(event)
        event.accept()

    def _list_key_pressed(self,event:object)->None:
        if event.key()==Qt.Key.Key_Delete and self.list.currentRow()>=0:self.removeManyRequested.emit(self._selected_indices(self.list.currentRow()))
        else:self.keyPressed.emit(event)
