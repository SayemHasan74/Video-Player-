"""Picture-in-picture placeholder window."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.settings import PIP_DEFAULT_SIZE, PIP_MINIMUM_SIZE


class PiPWindow(QWidget):
    """Small always-on-top placeholder for future video mirroring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Prism PiP")
        self.setMinimumSize(*PIP_MINIMUM_SIZE)
        self.resize(*PIP_DEFAULT_SIZE)
        self.setStyleSheet("background: #050505; color: #cfcfcf;")
        label = QLabel("Picture in Picture", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
