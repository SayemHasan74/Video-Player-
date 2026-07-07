"""Settings dialog."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QCheckBox, QDialog, QFileDialog, QFormLayout, QPushButton, QVBoxLayout

from config.settings import SettingsStore


class SettingsDialog(QDialog):
    """Basic preferences dialog."""

    def __init__(self, settings: SettingsStore, parent: object | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.always_on_top = QCheckBox("Always on top", self)
        self.always_on_top.setChecked(bool(settings.get("window.always_on_top", False)))
        self.hide_controls = QCheckBox("Hide controls while playing", self)
        self.hide_controls.setChecked(bool(settings.get("ui.hide_controls_while_playing", True)))
        self.screenshot_button = QPushButton(str(settings.get("paths.screenshot_dir", Path.home() / "Desktop")), self)
        form = QFormLayout()
        form.addRow(self.always_on_top)
        form.addRow(self.hide_controls)
        form.addRow("Screenshot folder", self.screenshot_button)
        save = QPushButton("Save", self)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save)
        self.screenshot_button.clicked.connect(self._choose_screenshot_dir)
        save.clicked.connect(self._save)

    def _choose_screenshot_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Screenshot Folder", self.screenshot_button.text())
        if path:
            self.screenshot_button.setText(path)

    def _save(self) -> None:
        self.settings.set("window.always_on_top", self.always_on_top.isChecked())
        self.settings.set("ui.hide_controls_while_playing", self.hide_controls.isChecked())
        self.settings.set("paths.screenshot_dir", self.screenshot_button.text())
        self.settings.save()
        self.accept()
