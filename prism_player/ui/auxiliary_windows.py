"""Welcome, history, inspector, filter and preference windows."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QFileInfo, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
    QFileIconProvider, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from config.settings import APP_VERSION, SettingsStore, app_data_dir
from core.keybindings import KeyBindingStore
from core.media_probe import probe_media
from ui.keybindings_editor import KeyBindingsEditor as ProfileKeyBindingsEditor
from utils.thumbnail import clear_thumbnail_cache


class WelcomeWindow(QWidget):
    openFiles = pyqtSignal(list)
    openUrl = pyqtSignal(str)

    def __init__(self, history: object, exclude_source: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Welcome to Comet")
        self.resize(720, 480)
        title = QLabel("Comet Player", self); title.setStyleSheet("font-size: 28px; font-weight: 650;")
        self.recent = QListWidget(self)
        provider = QFileIconProvider()
        for entry in history.entries(exclude_source=exclude_source):
            item = QListWidgetItem(f"{entry['title']}\n{entry['source']}")
            path = Path(entry["source"])
            if path.exists():
                item.setIcon(provider.icon(QFileInfo(str(path))))
            percent = int(100 * entry["position"] / entry["duration"]) if entry["duration"] else 0
            item.setToolTip(f"Watched {percent}% • {entry['updated_at']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.recent.addItem(item)
        open_file = QPushButton("Open File…", self); open_url = QPushButton("Open URL…", self)
        row = QHBoxLayout(); row.addWidget(open_file); row.addWidget(open_url); row.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(QLabel(f"Version {APP_VERSION}")); layout.addLayout(row); layout.addWidget(QLabel("Recent")); layout.addWidget(self.recent)
        open_file.clicked.connect(self._choose); open_url.clicked.connect(lambda: self.openUrl.emit(""))
        self.recent.itemDoubleClicked.connect(self._open_recent)
        self.setAcceptDrops(True)

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media")
        if files: self.openFiles.emit([Path(path) for path in files])

    def _open_recent(self, item: QListWidgetItem) -> None:
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if source.startswith(("http://", "https://")):
            self.openUrl.emit(source)
        elif source:
            self.openFiles.emit([Path(source)])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        urls = [url.toString() for url in event.mimeData().urls() if not url.isLocalFile()]
        if files:
            self.openFiles.emit(files)
        elif urls:
            self.openUrl.emit(urls[0])
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text.startswith(("http://", "https://")):
                self.openUrl.emit(text)
        event.acceptProposedAction()


class HistoryWindow(QDialog):
    openSource = pyqtSignal(str)

    def __init__(self, history: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True); self.history = history; self.setWindowTitle("History"); self.resize(760, 500)
        self.search = QLineEdit(self); self.search.setPlaceholderText("Search history…")
        self.list = QListWidget(self); remove = QPushButton("Remove"); clear = QPushButton("Clear All")
        self.list.setIconSize(QSize(48, 48))
        buttons = QHBoxLayout(); buttons.addWidget(remove); buttons.addWidget(clear); buttons.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(self.search); layout.addWidget(self.list); layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh); self.list.itemDoubleClicked.connect(lambda i: self.openSource.emit(i.data(Qt.ItemDataRole.UserRole)))
        remove.clicked.connect(self._remove); clear.clicked.connect(self._clear); self.refresh()

    def refresh(self, query: str = "") -> None:
        self.list.clear()
        provider = QFileIconProvider()
        for entry in self.history.entries(query):
            percent = int(100 * entry["position"] / entry["duration"]) if entry["duration"] else 0
            item = QListWidgetItem(f"{entry['title']}\n{percent}% watched  •  {entry['updated_at']}")
            path = Path(entry["source"])
            if path.exists():
                item.setIcon(provider.icon(QFileInfo(str(path))))
            item.setToolTip(entry["source"])
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.list.addItem(item)

    def _remove(self) -> None:
        if self.list.currentItem(): self.history.remove(self.list.currentItem().data(Qt.ItemDataRole.UserRole)); self.history.flush(); self.refresh(self.search.text())

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear History", "Remove all playback history?") == QMessageBox.StandardButton.Yes:
            self.history.clear(); self.history.flush(); self.refresh()


class InspectorWindow(QDialog):
    def __init__(self, player: object, source: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.player = player
        self.source = source
        self.setWindowTitle("Media Inspector")
        self.resize(760, 560)
        tabs = QTabWidget(self)
        data = probe_media(source)
        streams = data.get("streams", [])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        format_data = data.get("format", {})
        general = {
            "Container": format_data.get("format_long_name") or format_data.get("format_name"),
            "Video codec": video.get("codec_long_name") or video.get("codec_name"),
            "Audio codec": audio.get("codec_long_name") or audio.get("codec_name"),
            "Resolution": f"{video.get('width', 0)} × {video.get('height', 0)}",
            "Frame rate": video.get("avg_frame_rate") or video.get("r_frame_rate"),
            "Bitrate": format_data.get("bit_rate"),
        }
        tabs.addTab(self._mapping_page(general), "General")
        track_table = QTableWidget(len(streams), 6)
        track_table.setHorizontalHeaderLabels(["#", "Type", "Codec", "Language", "Title", "Details"])
        for row, stream in enumerate(streams):
            tags = stream.get("tags", {}) or {}
            details = f"{stream.get('width', '')}×{stream.get('height', '')}" if stream.get("codec_type") == "video" else f"{stream.get('channels', '')} ch"
            values = (stream.get("index"), stream.get("codec_type"), stream.get("codec_name"), tags.get("language"), tags.get("title"), details)
            for column, value in enumerate(values): track_table.setItem(row, column, QTableWidgetItem(str(value or "")))
        track_table.resizeColumnsToContents()
        tabs.addTab(track_table, "Tracks")
        path = Path(source)
        file_data = {
            "Path": source,
            "Size": path.stat().st_size if path.exists() else "Streaming source",
            "Duration": format_data.get("duration"),
            "Chapters": len(data.get("chapters", [])),
            "Format": format_data.get("format_long_name") or format_data.get("format_name"),
        }
        tabs.addTab(self._mapping_page(file_data), "File")
        status = QWidget()
        form = QFormLayout(status)
        self.status_values = {name: QLabel("—") for name in ("Decode FPS", "Display FPS", "Dropped frames", "A/V sync", "Cache")}
        for name, label in self.status_values.items(): form.addRow(name, label)
        self.watch = QLineEdit()
        self.watch.setPlaceholderText("e.g. video-params, demuxer-cache-duration")
        self.watch_value = QLabel("—")
        self.watch_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.watch_value.setWordWrap(True)
        form.addRow("Watch property", self.watch)
        form.addRow("Value", self.watch_value)
        tabs.addTab(status, "Status")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update)
        self.timer.start(1000)

    @staticmethod
    def _mapping_page(values: dict) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for name, value in values.items():
            label = QLabel(str(value if value not in (None, "") else "—"))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            form.addRow(name, label)
        return page

    def _update(self) -> None:
        mpv = self.player.mpv
        if mpv is None: return
        values = {
            "Decode FPS": self.player.get_property("container-fps", 0),
            "Display FPS": self.player.get_property("display-fps", 0),
            "Dropped frames": self.player.get_property("frame-drop-count", 0),
            "A/V sync": self.player.get_property("avsync", 0),
            "Cache": self.player.get_property("demuxer-cache-duration", 0),
        }
        for name, value in values.items(): self.status_values[name].setText(str(value or 0))
        name = self.watch.text().strip()
        if name:
            value = self.player.get_property(name, "Unavailable")
            self.watch_value.setText(json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value))
        else:
            self.watch_value.setText("—")


class PreferencesWindow(QDialog):
    def __init__(self, settings: SettingsStore, history: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True); self.settings = settings; self.history = history; self.keys = KeyBindingStore(); self.setWindowTitle("Preferences"); self.resize(900, 650)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search settings…")
        self.sections = QListWidget(); names = ["General", "UI", "Video/Codec", "Audio", "Subtitle", "Network", "Key Bindings", "Advanced", "Utilities"]
        self.sections.addItems(names); self.pages = QStackedWidget(); self.controls: dict[str, QWidget] = {}
        for name in names: self.pages.addWidget(self._page(name))
        body = QHBoxLayout(); body.addWidget(self.sections, 1); body.addWidget(self.pages, 4)
        save = QPushButton("Save"); layout = QVBoxLayout(self); layout.addWidget(self.search); layout.addLayout(body); layout.addWidget(save)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex); self.sections.setCurrentRow(0); self.search.textChanged.connect(self._filter); save.clicked.connect(self._save)

    def _page(self, name: str) -> QWidget:
        page = QWidget(); form = QFormLayout(page)
        specs = {
            "General": [("Resume playback", "playback.remember_position", "check"), ("Show welcome", "startup.show_welcome", "check"), ("Reopen last file", "startup.reopen_last", "check"), ("Open behavior", "playback.open_behavior", ["replace", "append", "new_window"]), ("Auto-resize on open", "playback.auto_resize", "check")],
            "UI": [("OSC position", "ui.osc_position", ["floating", "top", "bottom"]), ("Sidebar side", "ui.sidebar_side", ["left", "right"]), ("Theme", "ui.theme", ["dark", "system"]), ("Animations", "ui.animations", "check"), ("Hide controls while playing", "ui.hide_controls_while_playing", "check"), ("Hide delay (ms)", "ui.osc_hide_delay_ms", "spin"), ("Show OSD", "ui.show_osd", "check")],
            "Video/Codec": [("Hardware decoding", "video.hwdec", ["auto-safe", "auto", "no"]), ("Default aspect", "video.aspect", ["auto", "16:9", "4:3", "21:9"])],
            "Audio": [("Default volume", "playback.volume", "spin"), ("Audio device", "audio.device", "text"), ("Gapless playback", "audio.gapless", "check")],
            "Subtitle": [("Auto-load subtitles", "subtitle.autoload", "check"), ("Font", "subtitle.font", "text"), ("Size", "subtitle.size", "spin"), ("Color", "subtitle.color", "text"), ("Outline", "subtitle.outline", "spin"), ("Position", "subtitle.position", "spin"), ("Encoding", "subtitle.encoding", "text")],
            "Network": [("Proxy", "network.proxy", "text"), ("User agent", "network.user_agent", "text"), ("Preferred stream format", "network.preferred_format", "text")],
            "Advanced": [("Raw mpv options (one key=value per line; restart may be required)", "advanced.mpv_options", "multiline")],
        }.get(name, [])
        if name == "Key Bindings":
            editor=ProfileKeyBindingsEditor(self.keys,str(self.settings.get("keys.profile","Default"))); self.controls["keys.profile"] = editor.profile; form.addRow(editor)
        elif name == "Utilities":
            default_app = QPushButton("Register as media app")
            default_app.clicked.connect(self._set_default_app)
            clear_thumbnails = QPushButton("Clear thumbnail cache")
            clear_thumbnails.clicked.connect(self._clear_thumbnails)
            clear_history = QPushButton("Clear playback history")
            clear_history.clicked.connect(self._clear_history)
            reveal = QPushButton("Reveal config folder"); reveal.clicked.connect(lambda: os.startfile(app_data_dir()))
            form.addRow(default_app); form.addRow(clear_thumbnails); form.addRow(clear_history); form.addRow(reveal)
        for label, key, kind in specs:
            if kind == "check": widget = QCheckBox(); widget.setChecked(bool(self.settings.get(key, False)))
            elif kind == "spin":
                widget = QSpinBox()
                ranges = {"playback.volume": (0, 150), "subtitle.size": (10, 100), "subtitle.outline": (0, 10), "subtitle.position": (0, 150), "ui.osc_hide_delay_ms": (100, 30000)}
                widget.setRange(*ranges.get(key, (0, 100000))); widget.setValue(int(self.settings.get(key, 0)))
            elif isinstance(kind, list): widget = QComboBox(); widget.addItems(kind); widget.setCurrentText(str(self.settings.get(key, kind[0])))
            elif kind == "multiline": widget = QPlainTextEdit(str(self.settings.get(key, ""))); widget.setMinimumHeight(180)
            else: widget = QLineEdit(str(self.settings.get(key, "")))
            widget.setProperty("searchText", f"{name} {label} {key}".lower()); self.controls[key] = widget; form.addRow(label, widget)
        return page

    def _filter(self, text: str) -> None:
        text = text.lower().strip()
        for row in range(self.sections.count()):
            page = self.pages.widget(row); matches = not text or text in self.sections.item(row).text().lower() or any(text in str(child.property("searchText") or "") for child in page.findChildren(QWidget)); self.sections.item(row).setHidden(not matches)
        visible = next((row for row in range(self.sections.count()) if not self.sections.item(row).isHidden()), -1)
        current = self.sections.currentItem()
        if visible >= 0 and (current is None or current.isHidden()): self.sections.setCurrentRow(visible)

    def _set_default_app(self) -> None:
        if os.name != "nt":
            QMessageBox.information(self, "Default App", "File association registration is currently implemented for Windows.")
            return
        import winreg
        if getattr(sys, "frozen", False):
            command = f'"{sys.executable}" "%1"'
        else:
            entry = Path(__file__).resolve().parents[2] / "main.py"
            command = f'"{sys.executable}" "{entry}" "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\CometV2.Media") as key: winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Comet V2 media file")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\CometV2.Media\shell\open\command") as key: winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        for extension in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".flac", ".wav"):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{extension}\OpenWithProgids") as key: winreg.SetValueEx(key, "CometV2.Media", 0, winreg.REG_NONE, b"")
        QMessageBox.information(self, "Default App", "Comet V2 was registered in Windows ‘Open with’ choices.")

    def _clear_thumbnails(self) -> None:
        clear_thumbnail_cache()
        QMessageBox.information(self, "Thumbnail Cache", "Thumbnail cache cleared.")

    def _clear_history(self) -> None:
        if self.history is not None and QMessageBox.question(self, "Clear History", "Remove all playback history?") == QMessageBox.StandardButton.Yes:
            self.history.clear(); self.history.flush()
            QMessageBox.information(self, "History", "Playback history cleared.")

    def _save(self) -> None:
        for key, widget in self.controls.items():
            if isinstance(widget, QCheckBox): value = widget.isChecked()
            elif isinstance(widget, QSpinBox): value = widget.value()
            elif isinstance(widget, QComboBox): value = widget.currentText()
            elif isinstance(widget, QPlainTextEdit): value = widget.toPlainText()
            else: value = widget.text()
            self.settings.set(key, value)
        self.settings.save(); self.accept()
