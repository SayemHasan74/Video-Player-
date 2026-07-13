"""Reactive Video, Audio and Subtitle quick settings."""

from __future__ import annotations

import math
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class TrackSelector(QWidget):
    selected = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonClicked.connect(lambda button: self.selected.emit(button.property("trackId")))
        self.set_tracks([])

    def set_tracks(self, tracks: list[dict]) -> None:
        selected = self.current_data()
        for button in self.group.buttons():
            self.group.removeButton(button)
            button.deleteLater()
        while self.layout_box.count():
            item = self.layout_box.takeAt(0)
            if item.widget(): item.widget().setParent(None)
        entries = [("Off", "no")]
        for track in tracks:
            label = " • ".join(str(value) for value in (track.get("lang"), track.get("title")) if value) or f"Track {track.get('id')}"
            entries.append((label, track.get("id")))
        for label, track_id in entries:
            button = QRadioButton(label)
            button.setProperty("trackId", track_id)
            self.group.addButton(button)
            self.layout_box.addWidget(button)
            if track_id == selected or selected is None and track_id == "no": button.setChecked(True)

    def current_data(self) -> object:
        checked = self.group.checkedButton()
        return checked.property("trackId") if checked is not None else None

    def set_current(self, track_id: object) -> None:
        for button in self.group.buttons():
            if button.property("trackId") == track_id:
                button.setChecked(True)
                return


class ValueSlider(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, minimum: float, maximum: float, value: float = 0, decimals: int = 2) -> None:
        super().__init__()
        self.minimum = minimum
        self.maximum = maximum
        self.decimals = decimals
        self.scale = 10 ** decimals
        self.default = value
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(minimum * self.scale), round(maximum * self.scale))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(1 / self.scale if decimals else 1)
        self.spin.setFixedWidth(72)
        reset = QPushButton("↺")
        reset.setFixedWidth(28)
        reset.setToolTip("Reset")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        row.addWidget(reset)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        reset.clicked.connect(lambda: self.set_value(self.default, emit=True))
        self.set_value(value)

    def set_value(self, value: float, emit: bool = False) -> None:
        value = max(self.minimum, min(self.maximum, float(value)))
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(round(value * self.scale))
        self.spin.setValue(value)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
        if emit:
            self.changed.emit(value)

    def _slider_changed(self, value: int) -> None:
        number = value / self.scale
        self.spin.blockSignals(True)
        self.spin.setValue(number)
        self.spin.blockSignals(False)
        self.changed.emit(number)

    def _spin_changed(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * self.scale))
        self.slider.blockSignals(False)
        self.changed.emit(float(value))


class SpeedControl(QWidget):
    changed = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.25, 16.0)
        self.spin.setDecimals(2)
        self.spin.setSuffix("×")
        self.spin.setFixedWidth(78)
        presets = QHBoxLayout()
        for value in (0.5, 1.0, 1.5, 2.0):
            button = QPushButton(f"{value:g}×")
            button.clicked.connect(lambda _checked=False, speed=value: self.set_value(speed, emit=True))
            presets.addWidget(button)
        row = QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addLayout(presets)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(lambda value: self.set_value(value, emit=True, source="spin"))
        self.set_value(1.0)

    def set_value(self, value: float, emit: bool = False, source: str = "external") -> None:
        value = max(0.25, min(16.0, float(value)))
        position = round(1000 * math.log(value / 0.25, 64))
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(position)
        self.spin.setValue(value)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
        if emit:
            self.changed.emit(value)

    def _slider_changed(self, position: int) -> None:
        self.set_value(0.25 * math.pow(64, position / 1000), emit=True, source="slider")


class QuickSettingsPanel(QTabWidget):
    propertyChanged = pyqtSignal(str, object)
    findSubtitles = pyqtSignal()
    cropSelectionRequested = pyqtSignal()

    EQ_FREQUENCIES = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    EQ_PRESETS = {
        "Flat": [0] * 10,
        "Bass Boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
        "Treble Boost": [0, 0, 0, 0, 0, 1, 3, 4, 5, 6],
        "Vocal": [-2, -1, 0, 2, 4, 4, 3, 1, 0, -1],
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reacting = False
        self.controls: dict[str, Any] = {}
        self.addTab(self._video_page(), "Video")
        self.addTab(self._audio_page(), "Audio")
        self.addTab(self._subtitle_page(), "Subtitle")

    def _emit(self, prop: str, value: object) -> None:
        if not self._reacting:
            self.propertyChanged.emit(prop, value)

    def _combo(self, values: list[str], prop: str, editable: bool = False) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.setEditable(editable)
        combo.currentTextChanged.connect(lambda value: self._emit(prop, value))
        self.controls[prop] = combo
        return combo

    def _slider(self, lo: float, hi: float, value: float, prop: str, decimals: int = 2) -> ValueSlider:
        slider = ValueSlider(lo, hi, value, decimals)
        slider.changed.connect(lambda number: self._emit(prop, number))
        self.controls[prop] = slider
        return slider

    def _video_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("Aspect ratio", self._combo(["auto", "16:9", "4:3", "21:9", "1.85:1", "2.35:1"], "video-aspect-override", True))
        form.addRow("Rotate", self._combo(["0", "90", "180", "270"], "video-rotate"))
        crop_widget = QWidget()
        crop_layout = QGridLayout(crop_widget)
        crop_layout.setContentsMargins(0, 0, 0, 0)
        self.crop_values: dict[str, QSpinBox] = {}
        for column, name in enumerate(("w", "h", "x", "y")):
            spin = QSpinBox()
            spin.setRange(0, 16384)
            spin.setPrefix(f"{name}: ")
            spin.valueChanged.connect(self._crop_changed)
            self.crop_values[name] = spin
            crop_layout.addWidget(spin, 0, column)
        select_crop = QPushButton("Select on video…")
        clear_crop = QPushButton("Clear")
        select_crop.clicked.connect(self.cropSelectionRequested.emit)
        clear_crop.clicked.connect(self.clear_crop)
        crop_layout.addWidget(select_crop, 1, 0, 1, 2)
        crop_layout.addWidget(clear_crop, 1, 2, 1, 2)
        form.addRow("Crop", crop_widget)
        form.addRow("Hardware decoding", self._combo(["auto-safe", "auto", "no"], "hwdec"))
        for label, prop in (("Brightness", "brightness"), ("Contrast", "contrast"), ("Saturation", "saturation"), ("Gamma", "gamma"), ("Hue", "hue")):
            form.addRow(label, self._slider(-100, 100, 0, prop, 0))
        self.speed = SpeedControl()
        self.speed.changed.connect(lambda value: self._emit("speed", value))
        self.controls["speed"] = self.speed
        form.addRow("Speed 0.25×–16×", self.speed)
        return page

    def _audio_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.audio_tracks = TrackSelector()
        self.audio_tracks.selected.connect(lambda track_id: self._emit("aid", track_id))
        form.addRow("Track", self.audio_tracks)
        form.addRow("Delay", self._slider(-10, 10, 0, "audio-delay", 2))
        volume = self._slider(0, 150, 80, "volume", 0)
        volume.setToolTip("Values above 100% can clip or distort audio.")
        form.addRow("Volume boost", volume)
        warning = QLabel("Above 100% may clip or distort")
        warning.setStyleSheet("color:#c8a96b;font-size:11px;")
        form.addRow("", warning)
        self.eq_preset = QComboBox()
        self.eq_preset.addItems(list(self.EQ_PRESETS) + ["Custom"])
        self.eq_preset.currentTextChanged.connect(self._apply_eq_preset)
        form.addRow("EQ preset", self.eq_preset)
        bands = QWidget()
        row = QHBoxLayout(bands)
        row.setContentsMargins(0, 0, 0, 0)
        self.eq_sliders: list[QSlider] = []
        for frequency in self.EQ_FREQUENCIES:
            column = QVBoxLayout()
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-12, 12)
            slider.setValue(0)
            slider.setToolTip(f"{frequency} Hz")
            slider.valueChanged.connect(self._eq_changed)
            column.addWidget(slider, 1)
            column.addWidget(QLabel(f"{frequency // 1000}k" if frequency >= 1000 else str(frequency), alignment=Qt.AlignmentFlag.AlignCenter))
            row.addLayout(column)
            self.eq_sliders.append(slider)
        form.addRow("10-band EQ", bands)
        reset = QPushButton("Reset equalizer")
        reset.clicked.connect(lambda: self._set_eq([0] * 10, emit=True))
        form.addRow(reset)
        return page

    def _subtitle_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hide_subtitles = QCheckBox()
        self.hide_subtitles.toggled.connect(self._hide_all_changed)
        form.addRow("Hide all", self.hide_subtitles)
        self.primary_visible = QCheckBox("Visible")
        self.primary_visible.setChecked(True)
        self.primary_visible.toggled.connect(lambda checked: self._emit("sub-visibility", checked and not self.hide_subtitles.isChecked()))
        self.secondary_visible = QCheckBox("Visible")
        self.secondary_visible.setChecked(True)
        self.secondary_visible.toggled.connect(lambda checked: self._emit("secondary-sub-visibility", checked and not self.hide_subtitles.isChecked()))
        self.primary = QComboBox()
        self.secondary = QComboBox()
        self.primary.currentIndexChanged.connect(lambda _index: self._emit("sid", self.primary.currentData()))
        self.secondary.currentIndexChanged.connect(lambda _index: self._emit("secondary-sid", self.secondary.currentData()))
        primary_row = QHBoxLayout()
        primary_row.addWidget(self.primary, 1)
        primary_row.addWidget(self.primary_visible)
        secondary_row = QHBoxLayout()
        secondary_row.addWidget(self.secondary, 1)
        secondary_row.addWidget(self.secondary_visible)
        form.addRow("Primary", primary_row)
        form.addRow("Secondary", secondary_row)
        form.addRow("Primary delay", self._slider(-10, 10, 0, "sub-delay", 2))
        form.addRow("Secondary delay", self._slider(-10, 10, 0, "secondary-sub-delay", 2))
        self.font = QFontComboBox()
        self.font.currentFontChanged.connect(lambda font: self._emit("sub-font", font.family()))
        form.addRow("Font", self.font)
        form.addRow("Size", self._slider(10, 100, 42, "sub-font-size", 0))
        self.color = QLineEdit("#ffffff")
        color_button = QPushButton("Choose…")
        color_button.clicked.connect(self._choose_subtitle_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color, 1)
        color_row.addWidget(color_button)
        self.color.editingFinished.connect(lambda: self._emit("sub-color", self.color.text().strip()))
        form.addRow("Color", color_row)
        form.addRow("Outline", self._slider(0, 10, 2, "sub-border-size", 1))
        form.addRow("Shadow", self._slider(0, 10, 0, "sub-shadow-offset", 1))
        form.addRow("Position", self._slider(0, 150, 100, "sub-pos", 0))
        form.addRow("Encoding", self._combo(["auto", "UTF-8", "UTF-16", "CP1252", "ISO-8859-1", "GB18030", "Shift_JIS"], "sub-codepage", True))
        search = QPushButton("Search online subtitles…")
        search.clicked.connect(self.findSubtitles.emit)
        form.addRow(search)
        return page

    def _crop_changed(self) -> None:
        if self._reacting:
            return
        values = {name: spin.value() for name, spin in self.crop_values.items()}
        self.propertyChanged.emit("crop", values if values["w"] and values["h"] else None)

    def set_crop(self, width: int, height: int, x: int, y: int, emit: bool = True) -> None:
        self._reacting = True
        for name, value in (("w", width), ("h", height), ("x", x), ("y", y)):
            self.crop_values[name].setValue(max(0, int(value)))
        self._reacting = False
        if emit:
            self._crop_changed()

    def clear_crop(self) -> None:
        self.set_crop(0, 0, 0, 0, emit=False)
        self.propertyChanged.emit("crop", None)

    def _choose_subtitle_color(self) -> None:
        selected = QColorDialog.getColor(QColor(self.color.text()), self, "Subtitle Color")
        if selected.isValid():
            self.color.setText(selected.name(QColor.NameFormat.HexArgb))
            self._emit("sub-color", self.color.text())

    def _hide_all_changed(self, hidden: bool) -> None:
        self._emit("sub-visibility", self.primary_visible.isChecked() and not hidden)
        self._emit("secondary-sub-visibility", self.secondary_visible.isChecked() and not hidden)

    def _apply_eq_preset(self, name: str) -> None:
        if name in self.EQ_PRESETS:
            self._set_eq(self.EQ_PRESETS[name], emit=True)

    def _set_eq(self, values: list[int], emit: bool = False) -> None:
        for slider, value in zip(self.eq_sliders, values):
            slider.blockSignals(True)
            slider.setValue(int(value))
            slider.blockSignals(False)
        if emit:
            self._emit("audio-eq", self.eq_values())

    def _eq_changed(self) -> None:
        self.eq_preset.blockSignals(True)
        self.eq_preset.setCurrentText("Custom")
        self.eq_preset.blockSignals(False)
        self._emit("audio-eq", self.eq_values())

    def eq_values(self) -> dict[int, int]:
        return {frequency: slider.value() for frequency, slider in zip(self.EQ_FREQUENCIES, self.eq_sliders)}

    def set_tracks(self, audio: list[dict], subtitles: list[dict]) -> None:
        state = self._reacting
        self._reacting = True
        self.audio_tracks.set_tracks(audio)
        for combo, tracks in ((self.primary, subtitles), (self.secondary, subtitles)):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Off", "no")
            for track in tracks:
                label = " • ".join(str(value) for value in (track.get("lang"), track.get("title")) if value) or f"Track {track.get('id')}"
                combo.addItem(label, track.get("id"))
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self._reacting = state

    def set_state(self, state: dict[str, Any]) -> None:
        """React to mpv as the source of truth without feeding values back."""
        self._reacting = True
        try:
            for prop, control in self.controls.items():
                if prop not in state:
                    continue
                value = state[prop]
                if isinstance(control, ValueSlider):
                    control.set_value(float(value or 0))
                elif isinstance(control, SpeedControl):
                    control.set_value(float(value or 1))
                elif isinstance(control, QComboBox):
                    display = "auto" if prop == "video-aspect-override" and value == "no" else str(value)
                    control.setCurrentText(display)
            if "aid" in state:
                self.audio_tracks.set_current(state["aid"])
            for combo, prop in ((self.primary, "sid"), (self.secondary, "secondary-sid")):
                if prop in state:
                    index = combo.findData(state[prop])
                    if index >= 0:
                        combo.setCurrentIndex(index)
            if "sub-visibility" in state:
                self.hide_subtitles.setChecked(not bool(state["sub-visibility"]))
            if "secondary-sub-visibility" in state:
                self.secondary_visible.setChecked(bool(state["secondary-sub-visibility"]))
            if "sub-font" in state and state["sub-font"]:
                self.font.setCurrentFont(QFont(str(state["sub-font"])))
            if "sub-color" in state and state["sub-color"]:
                self.color.setText(str(state["sub-color"]))
        finally:
            self._reacting = False
