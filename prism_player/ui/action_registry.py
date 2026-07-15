"""Single command source shared by menus, shortcuts and player controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    label: str
    callback: Callable[..., Any]


class ActionRegistry(QObject):
    """Own command callbacks and the canonical QAction for each command."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._specs: dict[str, ActionSpec] = {}
        self._actions: dict[str, QAction] = {}

    def register(self, action_id: str, label: str, callback: Callable[..., Any]) -> None:
        if action_id in self._specs:
            raise ValueError(f"Action already registered: {action_id}")
        self._specs[action_id] = ActionSpec(action_id, label, callback)

    def callback(self, action_id: str) -> Callable[..., Any] | None:
        spec = self._specs.get(action_id)
        return spec.callback if spec is not None else None

    def callbacks(self) -> dict[str, Callable[..., Any]]:
        return {action_id: spec.callback for action_id, spec in self._specs.items()}

    def trigger(self, action_id: str, *args: Any, **kwargs: Any) -> Any:
        callback = self.callback(action_id)
        if callback is None:
            return None
        return callback(*args, **kwargs)

    def qaction(self, action_id: str, parent: QObject) -> QAction:
        action = self._actions.get(action_id)
        if action is not None:
            return action
        spec = self._specs[action_id]
        action = QAction(spec.label, parent)
        action.triggered.connect(lambda _checked=False, key=action_id: self.trigger(key))
        self._actions[action_id] = action
        return action

