"""Open URL dialog."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout


class OpenUrlDialog(QDialog):
    """Prompt for a playable URL."""

    urlAccepted = pyqtSignal(str)

    def __init__(self, initial_url: str = "", parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open URL")
        self.input = QLineEdit(initial_url, self)
        self.input.setPlaceholderText("https://...")
        open_button = QPushButton("Open", self)
        cancel_button = QPushButton("Cancel", self)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(open_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.input)
        layout.addLayout(buttons)
        open_button.clicked.connect(self._accept)
        cancel_button.clicked.connect(self.reject)

    def _accept(self) -> None:
        url = self.input.text().strip()
        if url:
            self.urlAccepted.emit(url)
            self.accept()
