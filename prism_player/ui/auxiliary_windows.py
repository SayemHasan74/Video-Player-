"""Welcome, history, inspector, filter and preference windows."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QEvent, QFileInfo, QPropertyAnimation, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
    QFileIconProvider, QGraphicsOpacityEffect, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from config.settings import APP_VERSION, SettingsStore, app_data_dir
from core.keybindings import KeyBindingStore
from core.media_probe import probe_media
from core.mpv_properties import (
    AVSYNC,
    CONTAINER_FPS,
    DEMUXER_CACHE_DURATION,
    DISPLAY_FPS,
    FRAME_DROP_COUNT,
)
from ui.keybindings_editor import KeyBindingsEditor as ProfileKeyBindingsEditor
from utils.file_utils import is_playlist_file
from utils.accessibility import system_animations_enabled, transitions_enabled
from utils.thumbnail import cached_thumbnails, clear_thumbnail_cache


class WelcomeWindow(QWidget):
    openFiles = pyqtSignal(list)
    openUrl = pyqtSignal(str)
    openFilesRequested = pyqtSignal(list, object)
    openUrlRequested = pyqtSignal(str, object)

    def __init__(self, history: object, exclude_source: str = "", parent: QWidget | None = None, settings: SettingsStore | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Welcome to Comet")
        self.resize(720, 480)
        title = QLabel("Comet Player", self); title.setStyleSheet("font-size: 28px; font-weight: 650;")
        self.recent = QListWidget(self)
        self.recent.setIconSize(QSize(96, 54))
        provider = QFileIconProvider()
        seen_sources: set[str] = set()
        history_entries = history.entries(exclude_source=exclude_source)
        thumbnails = cached_thumbnails([str(entry["source"]) for entry in history_entries])
        for entry in history_entries:
            source = str(entry["source"])
            if (
                settings is not None
                and not bool(settings.get("startup.show_playlist_recents", False))
                and not source.startswith(("http://", "https://"))
                and is_playlist_file(Path(source))
            ):
                continue
            seen_sources.add(source.casefold())
            item = QListWidgetItem(f"{entry['title']}\n{entry['source']}")
            path = Path(entry["source"])
            if source in thumbnails:
                item.setIcon(QIcon(thumbnails[source]))
            elif path.exists():
                item.setIcon(provider.icon(QFileInfo(str(path))))
            percent = int(100 * entry["position"] / entry["duration"]) if entry["duration"] else 0
            item.setToolTip(f"Watched {percent}% • {entry['updated_at']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.recent.addItem(item)
        if settings is not None and bool(settings.get("startup.show_playlist_recents", False)):
            playlist_recents = settings.get("startup.playlist_recents", [])
            for source in playlist_recents if isinstance(playlist_recents, list) else []:
                source = str(source)
                path = Path(source)
                if source.casefold() in seen_sources or not path.exists() or not is_playlist_file(path):
                    continue
                item = QListWidgetItem(f"{path.stem}\n{source}")
                item.setIcon(provider.icon(QFileInfo(source)))
                item.setToolTip("Playlist file")
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.recent.addItem(item)
                seen_sources.add(source.casefold())
        open_file = QPushButton("Open File…", self); open_folder = QPushButton("Open Folder…", self); open_url = QPushButton("Open URL…", self)
        row = QHBoxLayout(); row.addWidget(open_file); row.addWidget(open_folder); row.addWidget(open_url); row.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(QLabel(f"Version {APP_VERSION}")); layout.addLayout(row); layout.addWidget(QLabel("Recent")); layout.addWidget(self.recent)
        open_file.clicked.connect(self._choose); open_folder.clicked.connect(self._choose_folder); open_url.clicked.connect(lambda: self._emit_url("", QApplication.keyboardModifiers()))
        self.recent.itemDoubleClicked.connect(self._open_recent)
        self.setAcceptDrops(True)
        self._enable_drop_surface()

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media or Playlist", filter="Media and playlists (*.m3u *.m3u8);;All files (*)")
        if files: self._emit_files([Path(path) for path in files], QApplication.keyboardModifiers())

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Folder Recursively")
        if folder:
            self._emit_files([Path(folder)], QApplication.keyboardModifiers())

    def _open_recent(self, item: QListWidgetItem) -> None:
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if source.startswith(("http://", "https://")):
            self._emit_url(source, QApplication.keyboardModifiers())
        elif source:
            self._emit_files([Path(source)], QApplication.keyboardModifiers())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self._handle_drop(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DragEnter:
            self.dragEnterEvent(event)
            return event.isAccepted()
        if event.type() == QEvent.Type.Drop:
            self._handle_drop(event)
            return True
        return super().eventFilter(watched, event)

    def _enable_drop_surface(self) -> None:
        # Child labels/buttons otherwise become small dead zones over the
        # Welcome window, reproducing the old IINA icon-area drop bug.
        for widget in self.findChildren(QWidget):
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def _handle_drop(self, event: QDropEvent) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        urls = [url.toString() for url in event.mimeData().urls() if not url.isLocalFile()]
        if files:
            self._emit_files(files, event.modifiers())
        elif urls:
            self._emit_url(urls[0], event.modifiers())
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text.startswith(("http://", "https://")):
                self._emit_url(text, event.modifiers())
        event.acceptProposedAction()

    def _emit_files(self, files: list[Path], modifiers: object) -> None:
        self.openFiles.emit(files)
        self.openFilesRequested.emit(files, modifiers)

    def _emit_url(self, url: str, modifiers: object) -> None:
        self.openUrl.emit(url)
        self.openUrlRequested.emit(url, modifiers)


class HistoryWindow(QDialog):
    openSource = pyqtSignal(str)
    openSourceRequested = pyqtSignal(str, object)

    def __init__(self, history: object, parent: QWidget | None = None, settings: SettingsStore | None = None) -> None:
        super().__init__(parent); self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True); self.history = history; self.settings = settings; self.setWindowTitle("History"); self.resize(760, 500)
        self.search = QLineEdit(self); self.search.setPlaceholderText("Search history…")
        self.list = QListWidget(self); remove = QPushButton("Remove"); clear = QPushButton("Clear All")
        self.list.setIconSize(QSize(48, 48))
        self._opacity = QGraphicsOpacityEffect(self.list)
        self.list.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(100)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        buttons = QHBoxLayout(); buttons.addWidget(remove); buttons.addWidget(clear); buttons.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(self.search); layout.addWidget(self.list); layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh); self.list.itemDoubleClicked.connect(self._open_item)
        remove.clicked.connect(self._remove); clear.clicked.connect(self._clear); self.refresh()

    def refresh(self, query: str = "") -> None:
        self.list.clear()
        provider = QFileIconProvider()
        entries = self.history.entries(query)
        thumbnails = cached_thumbnails([str(entry["source"]) for entry in entries])
        for entry in entries:
            percent = int(100 * entry["position"] / entry["duration"]) if entry["duration"] else 0
            item = QListWidgetItem(f"{entry['title']}\n{percent}% watched  •  {entry['updated_at']}")
            path = Path(entry["source"])
            source = str(entry["source"])
            if source in thumbnails:
                item.setIcon(QIcon(thumbnails[source]))
            elif path.exists():
                item.setIcon(provider.icon(QFileInfo(str(path))))
            item.setToolTip(entry["source"])
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.list.addItem(item)
        self._animate_refresh()

    def _animate_refresh(self) -> None:
        enabled = transitions_enabled(self.settings) if self.settings is not None else system_animations_enabled()
        self._fade.stop()
        if not enabled:
            self._opacity.setOpacity(1.0)
            return
        self._fade.setStartValue(0.72)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _remove(self) -> None:
        if self.list.currentItem(): self.history.remove(self.list.currentItem().data(Qt.ItemDataRole.UserRole)); self.history.flush(); self.refresh(self.search.text())

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear History", "Remove all playback history?") == QMessageBox.StandardButton.Yes:
            self.history.clear(); self.history.flush(); self.refresh()

    def _open_item(self, item: QListWidgetItem) -> None:
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self.openSource.emit(source)
        self.openSourceRequested.emit(source, QApplication.keyboardModifiers())


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
        track_table = QTableWidget(len(streams), 8)
        track_table.setHorizontalHeaderLabels(["#", "Type", "Codec", "Language", "Title", "Default", "Forced", "Details"])
        for row, stream in enumerate(streams):
            tags = stream.get("tags", {}) or {}
            disposition = stream.get("disposition", {}) or {}
            if stream.get("codec_type") == "video":
                details = f"{stream.get('width', '')}×{stream.get('height', '')} • {stream.get('pix_fmt', '')}"
            elif stream.get("codec_type") == "audio":
                details = f"{stream.get('channels', '')} ch • {stream.get('sample_rate', '')} Hz"
            else:
                details = str(stream.get("codec_long_name") or "")
            values = (
                stream.get("index"), stream.get("codec_type"),
                stream.get("codec_long_name") or stream.get("codec_name"),
                tags.get("language"), tags.get("title"),
                "Yes" if disposition.get("default") else "", "Yes" if disposition.get("forced") else "",
                details,
            )
            metadata = json.dumps(stream, ensure_ascii=False, indent=2)
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setToolTip(metadata)
                track_table.setItem(row, column, cell)
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
        values = {
            "Decode FPS": self.player.get_property(CONTAINER_FPS, 0),
            "Display FPS": self.player.get_property(DISPLAY_FPS, 0),
            "Dropped frames": self.player.get_property(FRAME_DROP_COUNT, 0),
            "A/V sync": self.player.get_property(AVSYNC, 0),
            "Cache": self.player.get_property(DEMUXER_CACHE_DURATION, 0),
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
            "General": [("Resume playback", "playback.remember_position", "check"), ("Show welcome", "startup.show_welcome", "check"), ("Reopen last file", "startup.reopen_last", "check"), ("Single-file action (hold Alt to invert new window; Shift queues)", "playback.open_single_behavior", ["replace", "append", "new_window"]), ("Multiple-file action (hold Alt to invert new window; Shift queues)", "playback.open_multiple_behavior", ["replace", "append", "new_window"]), ("Show playlist files in Welcome recents", "startup.show_playlist_recents", "check"), ("Auto-resize on open", "playback.auto_resize", "check"), ("Automatically use Music Mode for audio-only media", "playback.auto_music_mode", "check"), ("Minimize starts PiP for video only", "window.minimize_to_pip_video", "check")],
            "UI": [("OSC position", "ui.osc_position", ["floating", "top", "bottom"]), ("Enable title bar and OSC", "ui.enableTitleBarAndOSC", "check"), ("Hide OSC when cursor leaves the window", "ui.hideOSCWhenCursorIsOutsideWindow", "check"), ("Don't hide cursor in fullscreen while OSC is visible", "ui.dontHideCursorInFullscreenWhileOSCIsVisible", "check"), ("Always show OSC and top chrome", "ui.osc_always_visible", "check"), ("Enable scroll over OSC seek/volume", "ui.osc_scroll_enabled", "check"), ("Enable scroll over video", "ui.video_scroll_enabled", "check"), ("Sidebar side", "ui.sidebar_side", ["left", "right"]), ("Pin Playlist sidebar", "ui.playlist_pinned", "check"), ("Pin Quick Settings opposite", "ui.quick_settings_pinned", "check"), ("Theme", "ui.theme", ["dark", "system"]), ("Disable window animations", "ui.disableWindowAnimation", "check"), ("Hide controls while playing", "ui.hide_controls_while_playing", "check"), ("Hide delay (ms)", "ui.osc_hide_delay_ms", "spin"), ("Show OSD", "ui.show_osd", "check"), ("OSD position", "ui.osd_position", ["top", "center", "bottom"]), ("Suppress OSD categories (comma-separated)", "ui.osd_suppressed_categories", "text"), ("Buffering indicator", "ui.buffering_throbber", ["off", "spinner", "text", "both"]), ("Music Mode: show album art/video", "music_mode.show_album_art", "check"), ("Music Mode: expand playlist by default", "music_mode.show_playlist", "check")],
            "Video/Codec": [
                ("Hardware decoding", "video.hwdec", ["no", "auto", "d3d11va"]),
                ("Fall back to software decoding", "video.hwdec_fallback", "check"),
                ("Default aspect", "video.aspect", ["auto", "16:9", "4:3", "21:9"]),
                ("Lock manual resize to video aspect", "video.lock_resize_aspect", "check"),
                ("Output color space (restart required)", "video.color_space", ["srgb", "display-p3"]),
                ("HDR handling", "video.hdr_mode", ["auto", "sdr", "passthrough"]),
                ("Tone mapping", "video.tone_mapping", ["auto", "bt.2390", "mobius", "reinhard", "hable", "clip"]),
                ("Gamut mapping", "video.gamut_mapping", ["auto", "perceptual", "relative", "desaturate", "clip"]),
                ("Dynamic HDR peak detection", "video.hdr_peak_detection", ["auto", "yes", "no"]),
                ("ICC profile path", "video.icc_profile", "text"),
            ],
            "Audio": [
                ("Default volume", "playback.volume", "spin"),
                ("Audio output device", "audio.device", "audio_device"),
                ("Gapless playback", "audio.gapless", ["no", "weak", "yes"]),
                ("ReplayGain", "audio.replaygain", ["no", "track", "album"]),
                ("ReplayGain preamp (dB)", "audio.replaygain_preamp", "signed_double"),
                ("Allow ReplayGain clipping", "audio.replaygain_clip", "check"),
                ("ReplayGain fallback (dB)", "audio.replaygain_fallback", "signed_double"),
                ("Preferred languages (ISO codes)", "audio.languages", "text"),
                ("DSD/DSF decoding", "audio.dsd_decode", ["pcm"]),
                ("Windows media keys / SMTC", "audio.media_keys", "check"),
            ],
            "Subtitle": [("Auto-load subtitles", "subtitle.autoload", "check"), ("Exclude embedded subtitles from automatic selection", "subtitle.exclude_embedded_auto", "check"), ("Font", "subtitle.font", "text"), ("Size", "subtitle.size", "spin"), ("Color", "subtitle.color", "text"), ("Outline", "subtitle.outline", "spin"), ("Position", "subtitle.position", "spin"), ("Encoding", "subtitle.encoding", "text")],
            "Network": [("Proxy", "network.proxy", "text"), ("User agent", "network.user_agent", "text"), ("Preferred stream format", "network.preferred_format", "text")],
            "Advanced": [
                ("mpv log verbosity", "advanced.mpv_loglevel", ["warn", "info", "debug", "trace"]),
                ("Raw mpv options (one key=value per line; restart may be required)", "advanced.mpv_options", "multiline"),
            ],
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
            elif kind == "signed_double":
                widget = QDoubleSpinBox(); widget.setRange(-15.0, 15.0); widget.setDecimals(1); widget.setSingleStep(0.5); widget.setValue(float(self.settings.get(key, 0.0)))
            elif kind == "audio_device":
                widget = QComboBox()
                parent = self.parentWidget(); player = getattr(parent, "player", None)
                devices = player.audio_devices() if player is not None else [{"name": "auto", "description": "System default"}]
                selected = str(self.settings.get(key, "auto"))
                for entry in devices:
                    widget.addItem(str(entry["description"]), str(entry["name"]))
                selected_index = widget.findData(selected)
                widget.setCurrentIndex(max(0, selected_index))
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
        for extension in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".dsf", ".dff", ".dsd", ".m3u", ".m3u8"):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{extension}\OpenWithProgids") as key: winreg.SetValueEx(key, "CometV2.Media", 0, winreg.REG_NONE, b"")
        QMessageBox.information(self, "Default App", "Comet V2 was registered in Windows ‘Open with’ choices.")

    def _clear_thumbnails(self) -> None:
        clear_thumbnail_cache()
        QMessageBox.information(self, "Thumbnail Cache", "Thumbnail cache cleared.")

    def _clear_history(self) -> None:
        if self.history is not None and QMessageBox.question(self, "Clear History", "Remove all playback history?") == QMessageBox.StandardButton.Yes:
            self.history.clear(); self.history.flush()
            self.settings.set("startup.playlist_recents", [])
            self.settings.save()
            QMessageBox.information(self, "History", "Playback history cleared.")

    def _save(self) -> None:
        for key, widget in self.controls.items():
            if isinstance(widget, QCheckBox): value = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): value = widget.value()
            elif isinstance(widget, QComboBox): value = widget.currentData() if key == "audio.device" else widget.currentText()
            elif isinstance(widget, QPlainTextEdit): value = widget.toPlainText()
            else: value = widget.text()
            self.settings.set(key, value)
        self.settings.save(); self.accept()
