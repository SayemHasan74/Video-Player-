"""Editable named keyboard-binding profiles with shortcut capture."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from core.keybindings import ACTION_LABELS, BUILTIN_PROFILES, KeyBindingStore


class ShortcutCapture(QKeySequenceEdit):
    """Capture printable special keys without losing the shifted character."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Qt can report '#' as Shift+3 on some Windows keyboard layouts.  The
        # printable character is the portable binding users actually chose.
        if event.text() == "#" and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.setKeySequence(QKeySequence("#"))
            event.accept()
            return
        super().keyPressEvent(event)


class KeyBindingsEditor(QWidget):
    bindingsSaved = pyqtSignal(str)

    def __init__(self, store: KeyBindingStore, profile: str) -> None:
        super().__init__()
        self.store = store
        self.profile = QComboBox()
        self.profile.addItems(store.profile_names())
        self.profile.setCurrentText(profile)
        self.read_only = QLabel()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search shortcuts or actions…")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        self.duplicate_button = QPushButton("Duplicate profile")
        self.delete_button = QPushButton("Delete profile")
        self.save_button = QPushButton("Save")
        reload_button = QPushButton("Reload")
        reveal = QPushButton("Reveal files")
        top = QHBoxLayout()
        top.addWidget(QLabel("Profile"))
        top.addWidget(self.profile, 1)
        top.addWidget(self.read_only)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.duplicate_button, self.delete_button, self.save_button, reload_button, reveal):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.profile.currentTextChanged.connect(self.reload)
        self.profile.view().doubleClicked.connect(lambda _index: self._rename_profile())
        self.search.textChanged.connect(self._filter_rows)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.delete_button.clicked.connect(self._delete)
        self.save_button.clicked.connect(self._save)
        reload_button.clicked.connect(lambda: self.reload(self.profile.currentText()))
        reveal.clicked.connect(lambda: os.startfile(self.store.directory))
        self.reload(profile)

    def reload(self, name: str) -> None:
        bindings = self.store.load(name)
        self.table.setRowCount(0)
        for shortcut, action in bindings.items():
            self._insert(shortcut, action)
        built_in = name in BUILTIN_PROFILES
        self.read_only.setText("Built-in • Read only" if built_in else "Custom")
        self.add_button.setEnabled(not built_in)
        self.remove_button.setEnabled(not built_in)
        self.save_button.setEnabled(not built_in)
        self.delete_button.setEnabled(not built_in)
        self.table.setEnabled(not built_in)
        self._filter_rows(self.search.text())

    def _insert(self, shortcut: str = "", action: str = "play_pause") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        capture = ShortcutCapture(QKeySequence(shortcut))
        capture.setClearButtonEnabled(True)
        action_combo = QComboBox()
        for action_id, label in ACTION_LABELS.items():
            action_combo.addItem(label, action_id)
        index = action_combo.findData(action)
        action_combo.setCurrentIndex(index if index >= 0 else 0)
        self.table.setCellWidget(row, 0, capture)
        self.table.setCellWidget(row, 1, action_combo)

    def _add(self) -> None:
        if self.profile.currentText() not in BUILTIN_PROFILES:
            self._insert()

    def _remove(self) -> None:
        if self.table.currentRow() >= 0 and self.profile.currentText() not in BUILTIN_PROFILES:
            self.table.removeRow(self.table.currentRow())

    def _duplicate(self) -> None:
        name, accepted = QInputDialog.getText(self, "Duplicate Profile", "New profile name:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.store.profile_names():
            QMessageBox.warning(self, "Duplicate Profile", "A profile with that name already exists.")
            return
        try:
            self.store.duplicate(self.profile.currentText(), name)
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicate Profile", str(exc))
            return
        self.profile.addItem(name)
        self.profile.setCurrentText(name)

    def _rename_profile(self) -> None:
        old_name = self.profile.currentText()
        if old_name in BUILTIN_PROFILES:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename Profile", "Profile name:", text=old_name
        )
        name = name.strip()
        if not accepted or not name or name == old_name:
            return
        try:
            self.store.rename(old_name, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Rename Profile", str(exc))
            return
        index = self.profile.findText(old_name)
        self.profile.setItemText(index, name)
        self.profile.setCurrentText(name)

    def _delete(self) -> None:
        name = self.profile.currentText()
        if name in BUILTIN_PROFILES:
            return
        if QMessageBox.question(self, "Delete Profile", f"Delete profile ‘{name}’?") != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        self.profile.removeItem(self.profile.findText(name))
        self.profile.setCurrentText("Default")

    def _save(self) -> None:
        name = self.profile.currentText()
        if name in BUILTIN_PROFILES:
            return
        bindings: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            capture = self.table.cellWidget(row, 0)
            action_combo = self.table.cellWidget(row, 1)
            shortcut = capture.keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            action = str(action_combo.currentData() or "")
            if not shortcut or not action:
                continue
            if shortcut in bindings:
                QMessageBox.warning(self, "Shortcut Conflict", f"{shortcut} is assigned more than once.")
                return
            bindings[shortcut] = action
        self.store.save(name, bindings)
        self.bindingsSaved.emit(name)
        QMessageBox.information(self, "Key Bindings", "Profile saved.")

    def _filter_rows(self, query: str) -> None:
        query = query.casefold().strip()
        for row in range(self.table.rowCount()):
            capture = self.table.cellWidget(row, 0)
            action_combo = self.table.cellWidget(row, 1)
            shortcut = capture.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            action = action_combo.currentText()
            self.table.setRowHidden(row, bool(query and query not in f"{shortcut} {action}".casefold()))
