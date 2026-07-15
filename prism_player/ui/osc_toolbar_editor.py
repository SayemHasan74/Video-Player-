"""Drag-and-drop editor for the OSC action toolbar."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from assets.icons import svg_icon
from ui.control_bar import DEFAULT_TOOLBAR, TOOLBAR_ACTIONS


class ToolbarList(QListWidget):
    """A move-only list that accepts actions from the peer list."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet(
            "QListWidget{background:#121419;border:1px solid #30343b;border-radius:8px;padding:5px;}"
            "QListWidget::item{padding:8px;border-radius:5px;}"
            "QListWidget::item:selected{background:#293241;}"
        )


class OscToolbarEditor(QDialog):
    """Move buttons between a palette and the active toolbar, then reorder."""

    def __init__(self, current: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize OSC Toolbar")
        self.resize(650, 430)
        self.available = ToolbarList(self)
        self.active = ToolbarList(self)
        self._populate(current)

        available_column = QVBoxLayout()
        available_column.addWidget(QLabel("Available controls"))
        available_column.addWidget(self.available)
        active_column = QVBoxLayout()
        active_column.addWidget(QLabel("Active toolbar — drag to reorder"))
        active_column.addWidget(self.active)
        lists = QHBoxLayout()
        lists.setSpacing(14)
        lists.addLayout(available_column, 1)
        lists.addLayout(active_column, 1)

        hint = QLabel("Drag controls between the lists. The same active order is reused in Floating, Top and Bottom OSC layouts.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aeb3bc;")
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(self._reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(reset)
        footer.addStretch(1)
        footer.addWidget(buttons)
        root = QVBoxLayout(self)
        root.addWidget(hint)
        root.addLayout(lists, 1)
        root.addLayout(footer)

    def selected_order(self) -> list[str]:
        return [str(self.active.item(row).data(Qt.ItemDataRole.UserRole)) for row in range(self.active.count())]

    def _populate(self, current: list[str]) -> None:
        active: list[str] = []
        for action_id in current:
            if action_id in TOOLBAR_ACTIONS and action_id not in active:
                active.append(action_id)
        if not active:
            active = DEFAULT_TOOLBAR.copy()
        for action_id in TOOLBAR_ACTIONS:
            self._add_item(self.active if action_id in active else self.available, action_id)
        # Restore the persisted order rather than the palette declaration order.
        items = {str(self.active.item(row).data(Qt.ItemDataRole.UserRole)): self.active.takeItem(row) for row in range(self.active.count() - 1, -1, -1)}
        for action_id in active:
            self.active.addItem(items[action_id])

    def _reset(self) -> None:
        for widget in (self.available, self.active):
            while widget.count():
                widget.takeItem(0)
        for action_id in TOOLBAR_ACTIONS:
            self._add_item(self.active if action_id in DEFAULT_TOOLBAR else self.available, action_id)

    @staticmethod
    def _add_item(target: QListWidget, action_id: str) -> None:
        icon, title = TOOLBAR_ACTIONS[action_id]
        item = QListWidgetItem(svg_icon(icon), title)
        item.setData(Qt.ItemDataRole.UserRole, action_id)
        target.addItem(item)
