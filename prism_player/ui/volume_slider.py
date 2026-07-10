"""Volume control widget."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from assets.icons import svg_icon
from ui.seekbar import LightBeamSlider


class VolumeWidget(QWidget):
    """Mute button plus volume slider."""

    volumeChanged = pyqtSignal(int)
    muteToggled = pyqtSignal()
    wheelAdjusted = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.button = QPushButton(self)
        self.button.setFixedSize(32, 32)
        self.button.setIcon(svg_icon("volume"))
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 0; outline: none; padding: 0; } "
            "QPushButton:hover { background: #242424; }"
        )
        self.slider = LightBeamSlider(self)
        self.slider.setRange(0, 150)
        self.slider.setValue(80)
        self.slider.setFixedWidth(92)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.button)
        layout.addWidget(self.slider)
        self.button.clicked.connect(self.muteToggled.emit)
        self.slider.valueChanged.connect(self.volumeChanged.emit)

    def set_volume_state(self, volume: int, muted: bool) -> None:
        """Update volume controls without loops."""
        self.slider.blockSignals(True)
        self.slider.setValue(volume)
        self.slider.blockSignals(False)
        self.button.setIcon(svg_icon("mute" if muted or volume <= 0 else "volume"))

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.wheelAdjusted.emit(5 if event.angleDelta().y() > 0 else -5)
        event.accept()
