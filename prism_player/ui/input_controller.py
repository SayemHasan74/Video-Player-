"""Application-wide player input routing."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
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
        input_event = event.type() in {
            QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel,
        }
        belongs_to_player = input_event and self._belongs_to_player(watched)
        if belongs_to_player:
            window._note_user_activity()
        if belongs_to_player and self._dispatch_plugin_input(watched, event, "before"):
            event.accept()
            return True
        media_keys = {
            Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaPause,
            Qt.Key.Key_MediaTogglePlayPause, Qt.Key.Key_MediaNext,
            Qt.Key.Key_MediaPrevious, Qt.Key.Key_MediaStop,
        }
        if (
            event.type() == QEvent.Type.KeyPress
            and not event.isAutoRepeat()
            and event.key() in media_keys
            and self._player_can_receive_input()
        ):
            self.handle_key(event)
            self._dispatch_plugin_input(watched, event, "after")
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if event.key() == Qt.Key.Key_Escape and self._player_can_receive_input():
                if window.osd.dismiss():
                    event.accept()
                    return True
                window._pause_and_minimize()
                self._dispatch_plugin_input(watched, event, "after")
                event.accept()
                return True
            if event.key() == Qt.Key.Key_Space and self._player_can_receive_input() and not self._focus_is_editing():
                self._trigger("play_pause", window.player.play_pause)
                self._dispatch_plugin_input(watched, event, "after")
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            if window.isVisible() and not window.isMinimized() and window.frameGeometry().contains(QCursor.pos()):
                if not window.window_modes.transitioning:
                    window._toggle_mini_mode()
                self._dispatch_plugin_input(watched, event, "after")
                event.accept()
                return True
        if event.type() == QEvent.Type.MouseButtonPress and window.playlist_panel.isVisible():
            widget = watched if isinstance(watched, QWidget) else None
            inside_panel = window.playlist_panel.rect().contains(window.playlist_panel.mapFromGlobal(QCursor.pos()))
            if not window._is_playlist_toggle_widget(widget) and not inside_panel and not window._is_playlist_widget(widget):
                window.sidebars.request_close_playlist()
        if belongs_to_player:
            self._queue_plugin_after(watched, event)
        return False

    def _dispatch_plugin_input(self, watched: object, event: QEvent, phase: str) -> bool:
        plugins = getattr(self.window, "plugins", None)
        dispatch = getattr(plugins, "dispatch_input", None)
        if not callable(dispatch):
            return False
        try:
            return bool(dispatch(self._plugin_event_payload(watched, event, phase), phase))
        except Exception:
            return False

    def _queue_plugin_after(self, watched: object, event: QEvent) -> None:
        plugins = getattr(self.window, "plugins", None)
        dispatch = getattr(plugins, "dispatch_input", None)
        if not callable(dispatch):
            return
        payload = self._plugin_event_payload(watched, event, "after")
        def run_after() -> None:
            try:
                dispatch(payload, "after")
            except Exception:
                pass
        QTimer.singleShot(0, run_after)

    @staticmethod
    def _plugin_event_payload(watched: object, event: QEvent, phase: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": event.type().name,
            "phase": phase,
            "target": type(watched).__name__,
        }
        for attribute in ("key", "text", "isAutoRepeat"):
            getter = getattr(event, attribute, None)
            if callable(getter):
                try:
                    payload[attribute] = getter()
                except (TypeError, RuntimeError):
                    pass
        for attribute in ("button", "buttons", "modifiers"):
            getter = getattr(event, attribute, None)
            if callable(getter):
                try:
                    value = getter()
                    payload[attribute] = int(getattr(value, "value", value))
                except (TypeError, RuntimeError, ValueError):
                    pass
        angle_delta = getattr(event, "angleDelta", None)
        if callable(angle_delta):
            try:
                delta = angle_delta()
                payload["wheel"] = (delta.x(), delta.y())
            except (TypeError, RuntimeError):
                pass
        return payload

    def _belongs_to_player(self, watched: object) -> bool:
        if watched is self.window:
            return True
        widget = watched if isinstance(watched, QWidget) else None
        return bool(widget is not None and (self.window.isAncestorOf(widget) or self.window._is_playlist_widget(widget)))

    def handle_key(self, event: QKeyEvent) -> None:
        window = self.window
        key = event.key()
        modifiers = event.modifiers()
        if key in {Qt.Key.Key_MediaPlay}:
            self._trigger("play", lambda: window.player.set_paused(False))
        elif key in {Qt.Key.Key_MediaPause}:
            self._trigger("pause", lambda: window.player.set_paused(True))
        elif key in {Qt.Key.Key_MediaTogglePlayPause}:
            self._trigger("play_pause", window.player.play_pause)
        elif key == Qt.Key.Key_MediaNext:
            self._trigger("next", window._play_next)
        elif key == Qt.Key.Key_MediaPrevious:
            self._trigger("previous", window._play_previous)
        elif key == Qt.Key.Key_MediaStop:
            self._trigger("stop", window.player.stop)
        elif key == Qt.Key.Key_Space:
            self._trigger("play_pause", window.player.play_pause)
        elif key == Qt.Key.Key_Left:
            self._trigger("seek_backward", lambda: window.player.seek_relative(-5))
        elif key == Qt.Key.Key_Right:
            self._trigger("seek_forward", lambda: window.player.seek_relative(5))
        elif key == Qt.Key.Key_Up:
            self._trigger("volume_up", lambda: window.player.change_volume(5))
        elif key == Qt.Key.Key_Down:
            self._trigger("volume_down", lambda: window.player.change_volume(-5))
        elif key == Qt.Key.Key_M and not modifiers & Qt.KeyboardModifier.ControlModifier:
            self._trigger("mute", window.player.toggle_mute)
        elif key == Qt.Key.Key_M and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._trigger("music_mode", window._toggle_mini_mode)
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if not window.isFullScreen():
                self._trigger("fullscreen", window._toggle_fullscreen)
        elif key == Qt.Key.Key_F:
            self._trigger("fullscreen", window._toggle_fullscreen)
        elif key == Qt.Key.Key_C:
            self._trigger("cover", window._toggle_cover_mode)
        elif key == Qt.Key.Key_Escape:
            if not window.osd.dismiss():
                window._pause_and_minimize()
        elif key == Qt.Key.Key_P:
            window._toggle_playlist()
        elif key == Qt.Key.Key_T:
            self._trigger("always_on_top", window._toggle_always_on_top)
        elif key == Qt.Key.Key_S:
            self._trigger("screenshot", window._save_screenshot)
        elif key == Qt.Key.Key_O and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._trigger("open_file", window.media_open.choose_files)
        elif key == Qt.Key.Key_U and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._trigger("open_url", window.media_open.show_url_dialog)
        elif key == Qt.Key.Key_Period:
            self._trigger("next", window._play_next)
        elif key == Qt.Key.Key_Comma:
            self._trigger("previous", window._play_previous)

    def _trigger(self, action_id: str, fallback: object) -> None:
        trigger = getattr(self.window, "trigger_action", None)
        if callable(trigger):
            trigger(action_id)
        elif callable(fallback):
            fallback()

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
