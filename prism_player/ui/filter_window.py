"""Live and persistent video/audio filter editor."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QComboBox,
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QDialogButtonBox,
    QSpinBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.filter_store import FilterStore
from core.keybindings import KeyBindingStore
from ui.keybindings_editor import ShortcutCapture


PRESETS: dict[str, list[tuple[str, str, Any]]] = {
    "crop": [("w", "int", (1, 16384, 1)), ("h", "int", (1, 16384, 1)), ("x", "int", (0, 16384, 1)), ("y", "int", (0, 16384, 1))],
    "expand": [("w", "int", (1, 16384, 1)), ("h", "int", (1, 16384, 1)), ("x", "int", (0, 16384, 1)), ("y", "int", (0, 16384, 1)), ("aspect", "text", ""), ("round", "int", (1, 128, 1))],
    "sharpen": [("amount", "float", (0.1, 5.0, 0.1)), ("matrix", "choose", [3, 5, 7])],
    "blur": [("amount", "float", (0.1, 5.0, 0.1)), ("matrix", "choose", [3, 5, 7])],
    "delogo": [("x", "int", (0, 16384, 1)), ("y", "int", (0, 16384, 1)), ("w", "int", (1, 16384, 1)), ("h", "int", (1, 16384, 1))],
    "negative": [],
    "vflip": [],
    "hflip": [],
    "lut3d": [("file", "text", ""), ("interpolation", "choose", ["nearest", "trilinear", "tetrahedral"])],
    "custom mpv": [("raw", "text", "")],
    "custom lavfi": [("raw", "text", "")],
}


class FloatParameter(QWidget):
    """Synchronized slider and decimal editor for generated float fields."""

    def __init__(self, minimum: float, maximum: float, step: float) -> None:
        super().__init__()
        self.step = float(step)
        self.editor = QDoubleSpinBox()
        self.editor.setRange(float(minimum), float(maximum))
        self.editor.setSingleStep(self.step)
        self.editor.setDecimals(max(2, len(str(step).partition(".")[2])))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, round((maximum - minimum) / self.step))
        self.slider.valueChanged.connect(
            lambda value: self.editor.setValue(float(minimum) + value * self.step)
        )
        self.editor.valueChanged.connect(
            lambda value: self.slider.setValue(round((value - float(minimum)) / self.step))
        )
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, 1); layout.addWidget(self.editor)

    def value(self) -> float:
        return self.editor.value()


class FiltersWindow(QDialog):
    applyFilter = pyqtSignal(str, str)
    removeFilter = pyqtSignal(str, str)
    savedFiltersChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, store: FilterStore | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.store = store or FilterStore()
        self.presets = self.store.load()
        self.parameters: dict[str, QWidget] = {}
        self.setWindowTitle("Filters")
        self.resize(760, 650)
        self.kind = QComboBox()
        self.kind.addItems(["Video", "Audio"])
        self.preset = QComboBox()
        self.parameter_widget = QWidget()
        self.parameter_form = QFormLayout(self.parameter_widget)
        self.active = QListWidget()
        self.saved = QListWidget()
        for listing in (self.active, self.saved):
            listing.setTextElideMode(Qt.TextElideMode.ElideNone)
            listing.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            listing.setWordWrap(False)
        self.saved.itemChanged.connect(self._saved_toggled)
        add = QPushButton("Add filter")
        remove = QPushButton("Remove active")
        save = QPushButton("Save active as preset…")
        edit = QPushButton("Edit saved…")
        delete = QPushButton("Delete saved")
        form = QFormLayout()
        form.addRow("Type", self.kind)
        form.addRow("Preset", self.preset)
        form.addRow(self.parameter_widget)
        active_buttons = QHBoxLayout()
        active_buttons.addWidget(add)
        active_buttons.addWidget(remove)
        active_buttons.addWidget(save)
        saved_buttons = QHBoxLayout()
        saved_buttons.addWidget(edit)
        saved_buttons.addWidget(delete)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(active_buttons)
        layout.addWidget(QLabel("Active filters"))
        layout.addWidget(self.active, 1)
        layout.addWidget(QLabel("Saved filters — check to toggle"))
        layout.addWidget(self.saved, 1)
        layout.addLayout(saved_buttons)
        self.kind.currentTextChanged.connect(self._populate_presets)
        self.preset.currentTextChanged.connect(self._build_parameter_form)
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        save.clicked.connect(self._save_active)
        edit.clicked.connect(self._edit_saved)
        delete.clicked.connect(self._delete_saved)
        self._populate_presets()
        self._refresh_saved()

    def set_active_filters(self, video: list, audio: list) -> None:
        selected = self.active.currentRow()
        self.active.clear()
        for kind, filters in (("video", video), ("audio", audio)):
            for entry in filters:
                value = self._filter_text(entry)
                item = QListWidgetItem(f"{kind.title()}  •  {value}")
                item.setToolTip(value)
                remove_value = f"@{entry.get('label')}" if isinstance(entry, dict) and entry.get("label") else value
                item.setData(Qt.ItemDataRole.UserRole, {"kind": kind, "value": value, "remove": remove_value})
                self.active.addItem(item)
        if self.active.count():
            self.active.setCurrentRow(min(max(0, selected), self.active.count() - 1))

    @staticmethod
    def _filter_text(entry: Any) -> str:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("label") or ""
            params = entry.get("params") or {}
            positional = [str(value) for key, value in sorted(params.items()) if str(key).startswith("@")]
            named = [f"{key}={value}" for key, value in params.items() if not str(key).startswith("@")]
            serialized = ":".join(positional + named)
            return f"{name}={serialized}" if serialized else str(name)
        return str(entry)

    def _populate_presets(self) -> None:
        current = self.preset.currentText()
        self.preset.blockSignals(True)
        self.preset.clear()
        names = list(PRESETS)
        if self.kind.currentText() == "Audio":
            names = ["custom mpv", "custom lavfi"]
        self.preset.addItems(names)
        self.preset.setCurrentText(current if current in names else names[0])
        self.preset.blockSignals(False)
        self._build_parameter_form(self.preset.currentText())

    def _clear_form(self) -> None:
        while self.parameter_form.rowCount():
            self.parameter_form.removeRow(0)
        self.parameters.clear()

    def _build_parameter_form(self, preset: str) -> None:
        self._clear_form()
        for name, kind, options in PRESETS.get(preset, []):
            if kind == "int":
                widget = QSpinBox()
                widget.setRange(options[0], options[1])
                widget.setSingleStep(options[2])
            elif kind == "float":
                widget = FloatParameter(options[0], options[1], options[2])
            elif kind == "choose":
                widget = QComboBox()
                widget.addItems([str(value) for value in options])
            else:
                widget = QLineEdit(str(options))
            self.parameters[name] = widget
            self.parameter_form.addRow(name.title(), widget)

    def _values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, widget in self.parameters.items():
            if isinstance(widget, (QSpinBox, QDoubleSpinBox, FloatParameter)):
                values[name] = widget.value()
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentText()
            else:
                values[name] = widget.text().strip()
        return values

    def _value(self) -> str:
        name = self.preset.currentText()
        values = self._values()
        if name == "custom mpv":
            return str(values.get("raw", ""))
        if name == "custom lavfi":
            return f"lavfi=[{values.get('raw', '')}]"
        if name in {"negative", "vflip", "hflip"}:
            return "lavfi=[negate]" if name == "negative" else name
        if name in {"sharpen", "blur"}:
            amount = float(values["amount"])
            if name == "blur":
                amount = -abs(amount)
            matrix = values["matrix"]
            return f"lavfi=[unsharp=luma_msize_x={matrix}:luma_msize_y={matrix}:luma_amount={amount:g}]"
        if name == "delogo":
            return f"lavfi=[delogo=x={values['x']}:y={values['y']}:w={values['w']}:h={values['h']}]"
        if name == "lut3d":
            path = str(values["file"]).replace("\\", "\\\\").replace("'", "\\'")
            return f"lavfi=[lut3d=file='{path}':interp={values['interpolation']}]"
        positional = ":".join(str(values[key]) for key in ("w", "h", "x", "y") if key in values)
        extras = ":".join(f"{key}={value}" for key, value in values.items() if key not in {"w", "h", "x", "y"} and value != "")
        return f"{name}={positional}{':' if positional and extras else ''}{extras}" if values else name

    def _add(self) -> None:
        value = self._value().strip()
        if not value:
            QMessageBox.warning(self, "Invalid filter", "Enter a filter value first.")
            return
        kind = self.kind.currentText().lower()
        self.applyFilter.emit(kind, value)

    def _remove(self) -> None:
        item = self.active.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(data, dict):
            self.removeFilter.emit(data["kind"], data.get("remove", data["value"]))

    def _save_active(self) -> None:
        item = self.active.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, dict):
            QMessageBox.information(self, "Save filter", "Select an active filter first.")
            return
        name, accepted = QInputDialog.getText(self, "Save Filter", "Preset name:")
        if not accepted or not name.strip():
            return
        shortcut, accepted = self._capture_shortcut()
        if not accepted:
            return
        if self._shortcut_conflict(shortcut):
            return
        self.presets.append({"name": name.strip(), "kind": data["kind"], "value": data["value"], "shortcut": shortcut, "enabled": True})
        self._persist()

    def _refresh_saved(self) -> None:
        self.saved.blockSignals(True)
        self.saved.clear()
        for index, preset in enumerate(self.presets):
            label = preset["name"] + (f"  [{preset['shortcut']}]" if preset.get("shortcut") else "")
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if preset.get("enabled") else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f"{preset['kind']}: {preset['value']}")
            self.saved.addItem(item)
        self.saved.blockSignals(False)

    def _saved_toggled(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(self.presets):
            return
        preset = self.presets[index]
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled != bool(preset.get("enabled")):
            preset["enabled"] = enabled
            (self.applyFilter if enabled else self.removeFilter).emit(preset["kind"], preset["value"])
            self._persist()

    def _edit_saved(self) -> None:
        item = self.saved.currentItem()
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(index, int):
            return
        preset = self.presets[index]
        name, ok = QInputDialog.getText(self, "Edit Preset", "Name:", text=preset["name"])
        if not ok or not name.strip():
            return
        value, ok = QInputDialog.getText(self, "Edit Preset", "Filter string:", text=preset["value"])
        if not ok or not value.strip():
            return
        shortcut, ok = self._capture_shortcut(preset.get("shortcut", ""))
        if not ok:
            return
        if self._shortcut_conflict(shortcut, index):
            return
        preset.update(name=name.strip(), value=value.strip(), shortcut=shortcut.strip())
        self._persist()

    def _capture_shortcut(self, initial: str = "") -> tuple[str, bool]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Filter Shortcut")
        capture = ShortcutCapture(QKeySequence(initial))
        capture.setClearButtonEnabled(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Press an optional shortcut, or clear it:"))
        layout.addWidget(capture)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return capture.keySequence().toString(QKeySequence.SequenceFormat.PortableText), accepted

    def _shortcut_conflict(self, shortcut: str, exclude_index: int = -1) -> bool:
        shortcut = QKeySequence(shortcut).toString(
            QKeySequence.SequenceFormat.PortableText
        ).strip()
        if not shortcut:
            return False
        for index, preset in enumerate(self.presets):
            existing = QKeySequence(str(preset.get("shortcut") or "")).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            if index != exclude_index and existing.casefold() == shortcut.casefold():
                QMessageBox.warning(
                    self, "Shortcut Conflict", f"{shortcut} is already used by {preset['name']}."
                )
                return True
        parent = self.parentWidget()
        settings = getattr(parent, "settings", None)
        profile = str(settings.get("keys.profile", "Default")) if settings is not None else "Default"
        parent_store = getattr(parent, "key_store", None)
        bindings = (parent_store or KeyBindingStore()).load(profile)
        used_shortcuts = {
            QKeySequence(value).toString(QKeySequence.SequenceFormat.PortableText).casefold()
            for value in bindings
        }
        if shortcut.casefold() in used_shortcuts:
            QMessageBox.warning(
                self, "Shortcut Conflict", f"{shortcut} is already used by the active key-binding profile."
            )
            return True
        return False

    def _delete_saved(self) -> None:
        item = self.saved.currentItem()
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(index, int):
            return
        preset = self.presets[index]
        if preset.get("enabled"):
            self.removeFilter.emit(preset["kind"], preset["value"])
        del self.presets[index]
        self._persist()

    def _persist(self) -> None:
        self.store.save(self.presets)
        self._refresh_saved()
        self.savedFiltersChanged.emit()
