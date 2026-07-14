"""Plugin manager UI."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from core.plugin_manager import PluginManager


class PluginWindow(QDialog):
    def __init__(self, manager: PluginManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Manage Plugins")
        self.resize(720, 430)
        self.list = QListWidget()
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        split = QSplitter(); split.addWidget(self.list); split.addWidget(self.details); split.setSizes([240, 480])
        self.toggle = QPushButton("Enable")
        reload_button = QPushButton("Reload")
        folder_button = QPushButton("Open Plugins Folder")
        data_button = QPushButton("Open Plugin Data")
        close_button = QPushButton("Close")
        buttons = QHBoxLayout()
        for button in (self.toggle, reload_button, folder_button, data_button): buttons.addWidget(button)
        buttons.addStretch(); buttons.addWidget(close_button)
        note = QLabel("Plugins are trusted local Python extensions. Only enable code you trust.")
        note.setStyleSheet("color:#aaa;")
        layout = QVBoxLayout(self); layout.addWidget(note); layout.addWidget(split, 1); layout.addLayout(buttons)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.toggle.clicked.connect(self._toggle)
        reload_button.clicked.connect(self._reload)
        folder_button.clicked.connect(lambda: self._open(self.manager.root))
        data_button.clicked.connect(lambda: self._open(self.manager.data_root))
        close_button.clicked.connect(self.close)
        self.manager.changed.connect(self.refresh)
        self.manager.error.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        selected = self._selected_id()
        self.list.blockSignals(True); self.list.clear()
        for plugin_id, record in sorted(self.manager.records.items(), key=lambda pair: pair[1].manifest.name.casefold()):
            state = "●" if record.module is not None else "○"
            item = QListWidgetItem(f"{state}  {record.manifest.name}")
            item.setData(Qt.ItemDataRole.UserRole, plugin_id)
            if record.error: item.setToolTip(record.error)
            self.list.addItem(item)
            if plugin_id == selected: self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count(): self.list.setCurrentRow(0)
        self._show_selected()

    def _selected_id(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _show_selected(self) -> None:
        record = self.manager.records.get(self._selected_id())
        if record is None:
            self.details.setHtml("<h3>No plugins found</h3><p>Put each plugin in its own folder with a plugin.json manifest.</p>")
            self.toggle.setEnabled(False)
            return
        manifest = record.manifest
        status = "Enabled" if record.module is not None else ("Failed" if record.error else "Disabled")
        error = f"<h4>Error</h4><pre>{record.error}</pre>" if record.error else ""
        self.details.setHtml(
            f"<h2>{manifest.name}</h2><p><b>{status}</b> · {manifest.version}</p>"
            f"<p>{manifest.description}</p><p><code>{manifest.plugin_id}</code></p>"
            f"<p>{manifest.root}</p>{error}"
        )
        self.toggle.setEnabled(True)
        self.toggle.setText("Disable" if record.enabled else "Enable")

    def _toggle(self) -> None:
        plugin_id = self._selected_id()
        record = self.manager.records.get(plugin_id)
        if record is not None:
            self.manager.set_enabled(plugin_id, not record.enabled)

    def _reload(self) -> None:
        plugin_id = self._selected_id()
        if plugin_id: self.manager.reload(plugin_id)
        else: self.manager.reload_all()

    @staticmethod
    def _open(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            QMessageBox.warning(None, "Open folder", str(exc))
