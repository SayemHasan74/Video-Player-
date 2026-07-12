"""Welcome, history, inspector, filter and preference windows."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from config.settings import APP_VERSION, SettingsStore, app_data_dir
from core.keybindings import KeyBindingStore
from core.media_probe import probe_media


class WelcomeWindow(QWidget):
    openFiles = pyqtSignal(list)
    openUrl = pyqtSignal()

    def __init__(self, history: object, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Welcome to Comet")
        self.resize(720, 480)
        title = QLabel("Comet Player", self); title.setStyleSheet("font-size: 28px; font-weight: 650;")
        self.recent = QListWidget(self)
        for entry in history.entries():
            item = QListWidgetItem(f"{entry['title']}\n{entry['source']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.recent.addItem(item)
        open_file = QPushButton("Open File…", self); open_url = QPushButton("Open URL…", self)
        row = QHBoxLayout(); row.addWidget(open_file); row.addWidget(open_url); row.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(QLabel(f"Version {APP_VERSION}")); layout.addLayout(row); layout.addWidget(QLabel("Recent")); layout.addWidget(self.recent)
        open_file.clicked.connect(self._choose); open_url.clicked.connect(self.openUrl.emit)
        self.recent.itemDoubleClicked.connect(lambda item: self.openFiles.emit([Path(item.data(Qt.ItemDataRole.UserRole))]))
        self.setAcceptDrops(True)

    def _choose(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media")
        if files: self.openFiles.emit([Path(path) for path in files])


class HistoryWindow(QDialog):
    openSource = pyqtSignal(str)

    def __init__(self, history: object, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.history = history; self.setWindowTitle("History"); self.resize(760, 500)
        self.search = QLineEdit(self); self.search.setPlaceholderText("Search history…")
        self.list = QListWidget(self); remove = QPushButton("Remove"); clear = QPushButton("Clear All")
        buttons = QHBoxLayout(); buttons.addWidget(remove); buttons.addWidget(clear); buttons.addStretch()
        layout = QVBoxLayout(self); layout.addWidget(self.search); layout.addWidget(self.list); layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh); self.list.itemDoubleClicked.connect(lambda i: self.openSource.emit(i.data(Qt.ItemDataRole.UserRole)))
        remove.clicked.connect(self._remove); clear.clicked.connect(self._clear); self.refresh()

    def refresh(self, query: str = "") -> None:
        self.list.clear()
        for entry in self.history.entries(query):
            percent = int(100 * entry["position"] / entry["duration"]) if entry["duration"] else 0
            item = QListWidgetItem(f"{entry['title']}  —  {percent}%  —  {entry['updated_at']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["source"]); self.list.addItem(item)

    def _remove(self) -> None:
        if self.list.currentItem(): self.history.remove(self.list.currentItem().data(Qt.ItemDataRole.UserRole)); self.refresh(self.search.text())

    def _clear(self) -> None: self.history.clear(); self.refresh()


class InspectorWindow(QDialog):
    def __init__(self, player: object, source: str, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.player = player; self.source = source; self.setWindowTitle("Media Inspector"); self.resize(700, 520)
        tabs = QTabWidget(self); data = probe_media(source)
        for name, value in (("General", data.get("format", {})), ("Tracks", data.get("streams", [])), ("File", {"path": source, "chapters": len(data.get("chapters", []))})):
            text = QLabel(json.dumps(value, indent=2, ensure_ascii=False), self); text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); text.setWordWrap(True)
            page = QWidget(); box = QVBoxLayout(page); box.addWidget(text); tabs.addTab(page, name)
        status = QWidget(); form = QFormLayout(status); self.status = QLabel(); self.watch = QLineEdit(); self.watch_value = QLabel(); form.addRow("Live status", self.status); form.addRow("Watch property", self.watch); form.addRow("Value", self.watch_value); tabs.addTab(status, "Status")
        layout = QVBoxLayout(self); layout.addWidget(tabs); self.timer = QTimer(self); self.timer.timeout.connect(self._update); self.timer.start(1000)

    def _update(self) -> None:
        mpv = self.player.mpv
        if mpv is None: return
        self.status.setText(f"FPS: {getattr(mpv, 'estimated_vf_fps', 0) or 0} | Dropped: {getattr(mpv, 'frame_drop_count', 0) or 0} | A/V: {getattr(mpv, 'avsync', 0) or 0}")
        name = self.watch.text().strip()
        if name:
            try: self.watch_value.setText(str(mpv._get_property(name)))
            except Exception: self.watch_value.setText("Unavailable")


class FiltersWindow(QDialog):
    applyFilter = pyqtSignal(str, str)
    removeFilter = pyqtSignal(str, str)
    PRESETS = ["crop", "expand", "sharpen", "blur", "delogo", "negative", "vflip", "hflip", "lut3d", "custom mpv", "custom lavfi"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setWindowTitle("Filters"); self.resize(620, 500)
        self.kind = QComboBox(); self.kind.addItems(["Video", "Audio"]); self.preset = QComboBox(); self.preset.addItems(self.PRESETS); self.params = QLineEdit(); self.params.setPlaceholderText("w:h:x:y or raw filter string")
        self.active = QListWidget(); self.saved = QListWidget(); add = QPushButton("Add"); remove = QPushButton("Remove"); save = QPushButton("Save preset")
        form = QFormLayout(); form.addRow("Type", self.kind); form.addRow("Preset", self.preset); form.addRow("Parameters", self.params)
        row = QHBoxLayout(); row.addWidget(add); row.addWidget(remove); row.addWidget(save)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addLayout(row); layout.addWidget(QLabel("Active filters")); layout.addWidget(self.active); layout.addWidget(QLabel("Saved filters")); layout.addWidget(self.saved)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); save.clicked.connect(self._save)

    def _value(self) -> str:
        name = self.preset.currentText(); params = self.params.text().strip()
        return params if name.startswith("custom") else f"{name}={params}" if params else name

    def _add(self) -> None:
        value = self._value(); self.active.addItem(value); self.applyFilter.emit(self.kind.currentText().lower(), value)

    def _remove(self) -> None:
        item = self.active.currentItem()
        if item: self.removeFilter.emit(self.kind.currentText().lower(), item.text()); self.active.takeItem(self.active.row(item))

    def _save(self) -> None:
        value = self._value(); self.saved.addItem(value)
        path = app_data_dir() / "filters.json"; existing = json.loads(path.read_text()) if path.exists() else []; existing.append(value); path.write_text(json.dumps(existing, indent=2))


class PreferencesWindow(QDialog):
    def __init__(self, settings: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.settings = settings; self.keys = KeyBindingStore(); self.setWindowTitle("Preferences"); self.resize(820, 600)
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
            "General": [("Resume playback", "playback.remember_position", "check"), ("Show welcome", "startup.show_welcome", "check")],
            "UI": [("OSC position", "ui.osc_position", ["floating", "top", "bottom"]), ("Sidebar side", "ui.sidebar_side", ["left", "right"]), ("Hide delay (ms)", "ui.osc_hide_delay_ms", "spin"), ("Show OSD", "ui.show_osd", "check")],
            "Video/Codec": [("Hardware decoding", "video.hwdec", ["auto-safe", "auto", "no"])],
            "Audio": [("Audio device", "audio.device", "text")],
            "Subtitle": [("Auto-load subtitles", "subtitle.autoload", "check"), ("Font", "subtitle.font", "text"), ("Size", "subtitle.size", "spin")],
            "Network": [("Proxy", "network.proxy", "text"), ("User agent", "network.user_agent", "text")],
            "Advanced": [("Raw mpv options", "advanced.mpv_options", "text")],
        }.get(name, [])
        if name == "Key Bindings":
            combo = QComboBox(); combo.addItems(self.keys.profile_names()); combo.setCurrentText(str(self.settings.get("keys.profile", "Default"))); self.controls["keys.profile"] = combo; form.addRow("Profile", combo)
        elif name == "Utilities":
            reveal = QPushButton("Reveal config folder"); reveal.clicked.connect(lambda: __import__('os').startfile(app_data_dir())); form.addRow(reveal)
        for label, key, kind in specs:
            if kind == "check": widget = QCheckBox(); widget.setChecked(bool(self.settings.get(key, False)))
            elif kind == "spin": widget = QSpinBox(); widget.setRange(0, 100000); widget.setValue(int(self.settings.get(key, 0)))
            elif isinstance(kind, list): widget = QComboBox(); widget.addItems(kind); widget.setCurrentText(str(self.settings.get(key, kind[0])))
            else: widget = QLineEdit(str(self.settings.get(key, "")))
            widget.setProperty("searchText", f"{name} {label} {key}".lower()); self.controls[key] = widget; form.addRow(label, widget)
        return page

    def _filter(self, text: str) -> None:
        text = text.lower().strip()
        for row in range(self.sections.count()):
            page = self.pages.widget(row); matches = not text or text in self.sections.item(row).text().lower() or any(text in str(child.property("searchText") or "") for child in page.findChildren(QWidget)); self.sections.item(row).setHidden(not matches)

    def _save(self) -> None:
        for key, widget in self.controls.items():
            if isinstance(widget, QCheckBox): value = widget.isChecked()
            elif isinstance(widget, QSpinBox): value = widget.value()
            elif isinstance(widget, QComboBox): value = widget.currentText()
            else: value = widget.text()
            self.settings.set(key, value)
        self.settings.save(); self.accept()
