"""Application-wide player input routing."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QCursor, QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)


class PlayerInputController(QObject):
    """Route shortcuts and outside-click behavior without native OS hooks."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        window = self.window
        if event.type() in {
            QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel,
        } and self._belongs_to_player(watched):
            window._note_user_activity()
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if event.key() == Qt.Key.Key_Escape and self._player_can_receive_input():
                window._pause_and_minimize()
                event.accept()
                return True
            if event.key() == Qt.Key.Key_Space and self._player_can_receive_input() and not self._focus_is_editing():
                window.player.play_pause()
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            if window.isVisible() and not window.isMinimized() and window.frameGeometry().contains(QCursor.pos()):
                if not window.window_modes.transitioning:
                    window._toggle_mini_mode()
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress and window.playlist_panel.isVisible():
            widget = watched if isinstance(watched, QWidget) else None
            inside_panel = window.playlist_panel.rect().contains(window.playlist_panel.mapFromGlobal(QCursor.pos()))
            if widget is not window.control_bar.playlist_button and not inside_panel and not window._is_playlist_widget(widget):
                window._set_playlist_visible(False)
        return False

    def _belongs_to_player(self, watched: object) -> bool:
        if watched is self.window:
            return True
        widget = watched if isinstance(watched, QWidget) else None
        return bool(widget is not None and (self.window.isAncestorOf(widget) or self.window._is_playlist_widget(widget)))

    def handle_key(self, event: QKeyEvent) -> None:
        window = self.window
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Space:
            window.player.play_pause()
        elif key == Qt.Key.Key_Left:
            window.player.seek_relative(-5)
        elif key == Qt.Key.Key_Right:
            window.player.seek_relative(5)
        elif key == Qt.Key.Key_Up:
            window.player.change_volume(5)
        elif key == Qt.Key.Key_Down:
            window.player.change_volume(-5)
        elif key == Qt.Key.Key_M and not modifiers & Qt.KeyboardModifier.ControlModifier:
            window.player.toggle_mute()
        elif key == Qt.Key.Key_M and modifiers & Qt.KeyboardModifier.ControlModifier:
            window._toggle_mini_mode()
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if not window.isFullScreen():
                window._toggle_fullscreen()
        elif key == Qt.Key.Key_F:
            window._toggle_fullscreen()
        elif key == Qt.Key.Key_C:
            window._toggle_cover_mode()
        elif key == Qt.Key.Key_Escape:
            window._pause_and_minimize()
        elif key == Qt.Key.Key_P:
            window._toggle_playlist()
        elif key == Qt.Key.Key_T:
            window._toggle_always_on_top()
        elif key == Qt.Key.Key_S:
            window._save_screenshot()
        elif key == Qt.Key.Key_O and modifiers & Qt.KeyboardModifier.ControlModifier:
            window._choose_files()
        elif key == Qt.Key.Key_U and modifiers & Qt.KeyboardModifier.ControlModifier:
            window._show_url_dialog("")
        elif key == Qt.Key.Key_Period:
            window._play_next()
        elif key == Qt.Key.Key_Comma:
            window._play_previous()

    def _player_can_receive_input(self) -> bool:
        window = self.window
        focus = QApplication.focusWidget()
        in_player = focus is None or focus is window or (
            focus is not None and (window.isAncestorOf(focus) or window._is_playlist_widget(focus))
        )
        return QApplication.activeModalWidget() is None and in_player

    @staticmethod
    def _focus_is_editing() -> bool:
        return isinstance(
            QApplication.focusWidget(),
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QAbstractButton),
        )
