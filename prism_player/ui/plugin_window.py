"""Plugin manager UI."""

from __future__ import annotations

import os
import html
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget,
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
        self.preference_page = QWidget()
        self.preference_form = QFormLayout(self.preference_page)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        tabs = QTabWidget()
        tabs.addTab(self.details, "Details")
        tabs.addTab(self.preference_page, "Preferences")
        tabs.addTab(self.logs, "Logs")
        split = QSplitter(); split.addWidget(self.list); split.addWidget(tabs); split.setSizes([240, 480])
        self.toggle = QPushButton("Enable")
        reload_button = QPushButton("Reload")
        folder_button = QPushButton("Open Plugins Folder")
        data_button = QPushButton("Open Plugin Data")
        script_button = QPushButton("User Script…")
        clear_logs = QPushButton("Clear Logs")
        close_button = QPushButton("Close")
        buttons = QHBoxLayout()
        for button in (self.toggle, reload_button, folder_button, data_button, script_button, clear_logs): buttons.addWidget(button)
        buttons.addStretch(); buttons.addWidget(close_button)
        note = QLabel("Plugins are trusted local Python extensions. Only enable code you trust.")
        note.setStyleSheet("color:#aaa;")
        layout = QVBoxLayout(self); layout.addWidget(note); layout.addWidget(split, 1); layout.addLayout(buttons)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.toggle.clicked.connect(self._toggle)
        reload_button.clicked.connect(self._reload)
        folder_button.clicked.connect(lambda: self._open(self.manager.root))
        data_button.clicked.connect(lambda: self._open(self.manager.data_root))
        script_button.clicked.connect(self._user_script)
        clear_logs.clicked.connect(self.manager.clear_logs)
        close_button.clicked.connect(self.close)
        self.manager.changed.connect(self.refresh)
        self.manager.error.connect(lambda *_: self.refresh())
        self.manager.preferencesChanged.connect(lambda *_: self._show_selected())
        self.manager.logChanged.connect(self._refresh_logs)
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
            self._build_preferences(None)
            self._refresh_logs()
            return
        manifest = record.manifest
        status = "Enabled" if record.module is not None else ("Failed" if record.error else "Disabled")
        error = f"<h4>Error</h4><pre>{html.escape(record.error)}</pre>" if record.error else ""
        self.details.setHtml(
            f"<h2>{html.escape(manifest.name)}</h2><p><b>{status}</b> · {html.escape(manifest.version)}</p>"
            f"<p>{html.escape(manifest.description)}</p><p><code>{html.escape(manifest.plugin_id)}</code></p>"
            f"<p>{html.escape(str(manifest.root))}</p>{error}"
        )
        self.toggle.setEnabled(True)
        self.toggle.setText("Disable" if record.enabled else "Enable")
        self._build_preferences(record)
        self._refresh_logs()

    def _build_preferences(self, record: object | None) -> None:
        while self.preference_form.rowCount():
            self.preference_form.removeRow(0)
        if record is None or not record.preference_schema or record.preferences is None:
            self.preference_form.addRow(QLabel("This plugin has no declared preferences."))
            return
        for field in record.preference_schema:
            key, kind = str(field["key"]), str(field["type"])
            value = record.preferences.get(key, field.get("default"))
            if kind == "check":
                widget = QCheckBox(); widget.setChecked(bool(value)); signal = widget.toggled
            elif kind == "int":
                widget = QSpinBox(); widget.setRange(int(field.get("min", -1_000_000)), int(field.get("max", 1_000_000))); widget.setSingleStep(int(field.get("step", 1))); widget.setValue(int(value or 0)); signal = widget.valueChanged
            elif kind == "float":
                widget = QDoubleSpinBox(); widget.setRange(float(field.get("min", -1_000_000)), float(field.get("max", 1_000_000))); widget.setSingleStep(float(field.get("step", 0.1))); widget.setValue(float(value or 0)); signal = widget.valueChanged
            elif kind == "choose":
                widget = QComboBox(); widget.addItems([str(option) for option in field.get("options", [])]); widget.setCurrentText(str(value or "")); signal = widget.currentTextChanged
            else:
                widget = QLineEdit(str(value or "")); signal = widget.textChanged
            signal.connect(lambda changed, prefs=record.preferences, name=key: prefs.set(name, changed))
            self.preference_form.addRow(str(field["label"]), widget)

    def _refresh_logs(self) -> None:
        selected = self._selected_id()
        lines = []
        for entry in self.manager.logs:
            if selected and entry.owner != selected:
                continue
            timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
            lines.append(f"{timestamp}  {entry.level.upper():7}  [{entry.owner}] {entry.message}")
        self.logs.setPlainText("\n".join(lines))
        self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())

    def _user_script(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Quick User Script")
        dialog.resize(680, 500)
        name = QLineEdit("My Script")
        code = QPlainTextEdit(
            "# The global `api` object is ready to use.\n"
            "api.logging.info('User Script started')\n"
            "api.core.osd('Hello from a User Script')\n"
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save && Run")
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Name")); layout.addWidget(name)
        layout.addWidget(QLabel("Python snippet")); layout.addWidget(code, 1); layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            path = self.manager.save_user_script(name.text(), code.toPlainText())
            if not self.manager.run_user_script(path.stem):
                raise RuntimeError("Script failed; see Logs for details")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "User Script", str(exc))

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
