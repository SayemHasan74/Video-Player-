"""Reactive Video, Audio and Subtitle quick settings."""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget


class ValueSlider(QWidget):
    changed = pyqtSignal(float)
    def __init__(self, minimum: float, maximum: float, value: float = 0, scale: int = 100) -> None:
        super().__init__(); self.scale = scale; self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(round(minimum*scale), round(maximum*scale)); self.slider.setValue(round(value*scale)); self.value = QLabel(f"{value:g}")
        row = QHBoxLayout(self); row.setContentsMargins(0,0,0,0); row.addWidget(self.slider); row.addWidget(self.value)
        self.slider.valueChanged.connect(self._emit)
    def _emit(self, value: int) -> None:
        number=value/self.scale; self.value.setText(f"{number:g}"); self.changed.emit(number)


class QuickSettingsPanel(QTabWidget):
    propertyChanged = pyqtSignal(str, object)
    findSubtitles = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.addTab(self._video(), "Video"); self.addTab(self._audio(), "Audio"); self.addTab(self._subtitle(), "Subtitle")

    def _combo(self, values: list[str], prop: str) -> QComboBox:
        combo=QComboBox(); combo.addItems(values); combo.currentTextChanged.connect(lambda value:self.propertyChanged.emit(prop,value)); return combo
    def _slider(self, lo: float, hi: float, value: float, prop: str, scale: int=100) -> ValueSlider:
        slider=ValueSlider(lo,hi,value,scale); slider.changed.connect(lambda number:self.propertyChanged.emit(prop,number)); return slider

    def _video(self) -> QWidget:
        page=QWidget(); form=QFormLayout(page)
        form.addRow("Aspect",self._combo(["auto","16:9","4:3","21:9"],"video-aspect-override")); form.addRow("Rotate",self._combo(["0","90","180","270"],"video-rotate")); crop=QLineEdit(); crop.setPlaceholderText("w:h:x:y"); crop.editingFinished.connect(lambda:self.propertyChanged.emit("crop",crop.text())); form.addRow("Crop",crop); form.addRow("Hardware decode",self._combo(["auto-safe","auto","no"],"hwdec"))
        for label,prop in (("Brightness","brightness"),("Contrast","contrast"),("Saturation","saturation"),("Gamma","gamma"),("Hue","hue")): form.addRow(label,self._slider(-100,100,0,prop,1))
        speed=QSlider(Qt.Orientation.Horizontal); speed.setRange(0,1000); speed.setValue(400); speed.valueChanged.connect(lambda value:self.propertyChanged.emit("speed",0.25*math.pow(64,value/1000))); form.addRow("Speed 0.25×–16×",speed)
        presets=QHBoxLayout()
        for value in (.5,1,1.5,2): button=QPushButton(f"{value:g}×"); button.clicked.connect(lambda _=False,v=value:self.propertyChanged.emit("speed",v)); presets.addWidget(button)
        form.addRow("Presets",presets); return page

    def _audio(self) -> QWidget:
        page=QWidget(); form=QFormLayout(page); self.audio_tracks=QComboBox(); self.audio_tracks.currentIndexChanged.connect(lambda _index:self.propertyChanged.emit("aid",self.audio_tracks.currentData())); form.addRow("Track",self.audio_tracks); form.addRow("Delay",self._slider(-10,10,0,"audio-delay")); form.addRow("Volume boost",self._slider(0,150,80,"volume",1))
        bands=QWidget(); row=QHBoxLayout(bands); row.setContentsMargins(0,0,0,0)
        for frequency in (31,62,125,250,500,1000,2000,4000,8000,16000): slider=QSlider(Qt.Orientation.Vertical); slider.setRange(-12,12); slider.setToolTip(f"{frequency} Hz"); row.addWidget(slider)
        form.addRow("10-band EQ",bands); return page

    def _subtitle(self) -> QWidget:
        page=QWidget(); form=QFormLayout(page); hide=QCheckBox(); hide.toggled.connect(lambda checked:self.propertyChanged.emit("sub-visibility",not checked)); form.addRow("Hide all",hide); self.primary=QComboBox(); self.secondary=QComboBox(); self.primary.currentIndexChanged.connect(lambda _index:self.propertyChanged.emit("sid",self.primary.currentData())); self.secondary.currentIndexChanged.connect(lambda _index:self.propertyChanged.emit("secondary-sid",self.secondary.currentData())); form.addRow("Primary",self.primary); form.addRow("Secondary",self.secondary); form.addRow("Primary delay",self._slider(-10,10,0,"sub-delay")); form.addRow("Font",QLineEdit("Segoe UI")); form.addRow("Size",self._slider(10,100,42,"sub-font-size",1)); form.addRow("Position",self._slider(0,150,100,"sub-pos",1)); search=QPushButton("Search online subtitles…"); search.clicked.connect(self.findSubtitles.emit); form.addRow(search); return page

    def set_tracks(self, audio: list[dict], subtitles: list[dict]) -> None:
        for combo,tracks in ((self.audio_tracks,audio),(self.primary,subtitles),(self.secondary,subtitles)):
            combo.blockSignals(True); combo.clear(); combo.addItem("Off","no")
            for track in tracks: combo.addItem(track.get("title") or track.get("lang") or f"Track {track.get('id')}",track.get("id"))
            combo.blockSignals(False)
