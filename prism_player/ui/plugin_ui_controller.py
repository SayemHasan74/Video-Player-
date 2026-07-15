"""Plugin runtime ownership and its Qt menu/sidebar integration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QLabel, QWidget

from core.plugin_manager import PluginManager
from ui.plugin_window import PluginWindow
from utils.file_utils import is_probable_url


class PluginUiController(QObject):
    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.manager = PluginManager(self)
        self.dialog: PluginWindow | None = None
        self.overlay_widgets: dict[str, QLabel] = {}
        self.manager.changed.connect(self.refresh)
        self.manager.error.connect(self._error)
        self.manager.overlayChanged.connect(self.refresh_overlays)

    @property
    def player(self) -> Any:
        return self.window.player

    @property
    def osd(self) -> Any:
        return self.window.osd

    def load_enabled(self) -> None:
        self.manager.load_enabled()
        self.refresh()

    def show_manager(self) -> None:
        self.manager.discover()
        if self.dialog is None:
            self.dialog = PluginWindow(self.manager, self.window)
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_folder(self) -> None:
        self.manager.root.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(self.manager.root)  # type: ignore[attr-defined]
        except OSError as exc:
            self.osd.show_message(f"Could not open plugin folder: {exc}", "error")

    def refresh(self) -> None:
        window = self.window
        menu = window._plugin_menu
        if menu is not None:
            menu.clear()
            for action_id in ("manage_plugins", "reload_plugins", "plugin_folder"):
                action = window._menu_actions.get(action_id)
                if action is not None:
                    menu.addAction(action)
            items = self.manager.menu_items("plugin")
            if items:
                menu.addSeparator()
            for item in items:
                action = menu.addAction(item.title)
                try:
                    action.setEnabled(bool(item.enabled() if callable(item.enabled) else item.enabled))
                except Exception:
                    action.setEnabled(False)
                action.triggered.connect(
                    lambda _checked=False, contribution=item: self.manager.invoke(contribution)
                )
        window.playlist_panel.clear_plugin_tabs()
        for item in self.manager.sidebar_items():
            try:
                widget = item.factory()
                if not isinstance(widget, QWidget):
                    widget = QLabel(str(widget))
                    widget.setWordWrap(True)
                window.playlist_panel.add_plugin_tab(
                    f"{item.owner}:{item.item_id}", item.title, widget
                )
            except Exception as exc:
                self._error(item.owner, str(exc))
        context_items = [
            (
                item.title,
                lambda index, source, contribution=item: self.manager.invoke(
                    contribution, index, source
                ),
            )
            for item in self.manager.menu_items("playlist_context")
        ]
        window.playlist_panel.set_plugin_context_items(context_items)
        self.refresh_overlays()

    def refresh_overlays(self) -> None:
        active: set[str] = set()
        for item in self.manager.overlay_items():
            key = f"{item.owner}:{item.item_id}"
            active.add(key)
            label = self.overlay_widgets.get(key)
            if label is None:
                label = QLabel(self.window.video)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
                self.overlay_widgets[key] = label
            label.setProperty("pluginPosition", item.position)
            label.setText(item.html)
            label.setStyleSheet(
                "background:transparent;color:white;padding:6px;" + item.style
            )
            label.adjustSize()
            label.show()
            label.raise_()
        for key in set(self.overlay_widgets) - active:
            self.overlay_widgets.pop(key).deleteLater()
        self.position_overlays()

    def position_overlays(self) -> None:
        width, height, margin = self.window.video.width(), self.window.video.height(), 16
        for label in self.overlay_widgets.values():
            position = str(label.property("pluginPosition") or "top-left")
            x = margin if position.endswith("left") else max(margin, width - label.width() - margin) if position.endswith("right") else max(margin, (width - label.width()) // 2)
            y = margin if position.startswith("top") else max(margin, height - label.height() - margin) if position.startswith("bottom") else max(margin, (height - label.height()) // 2)
            label.move(x, y)
            label.raise_()

    def plugin_player_status(self) -> dict[str, object]:
        window = self.window
        current = window.playlist.current_item()
        return {
            "source": current.source if current else "",
            "title": current.title if current else "",
            "position": window.session.position,
            "duration": window.session.duration,
            "paused": not window._is_playing,
            "playlist_index": window.playlist.current_index,
            "window_mode": window.window_modes.mode.name.lower(),
            "window_frame": {
                "x": window.x(), "y": window.y(),
                "width": window.width(), "height": window.height(),
            },
            "fullscreen": window.isFullScreen(),
            "volume": window.player.get_property("volume", 0),
            "muted": bool(window.player.get_property("mute", False)),
            "speed": window.player.get_property("speed", 1.0),
            "audio_tracks": list(window.audio_tracks),
            "subtitle_tracks": list(window.subtitle_tracks),
        }

    def plugin_playlist_items(self) -> list[dict[str, object]]:
        return [
            {
                "index": index,
                "source": item.source,
                "title": item.title,
                "duration": item.duration,
                "is_url": item.is_url,
            }
            for index, item in enumerate(self.window.playlist.items)
        ]

    def plugin_playlist_add(self, source: str, play: bool = False) -> None:
        window = self.window
        if is_probable_url(source):
            window.open_url(source)
            return
        path = Path(source).expanduser()
        if path.exists():
            window.open_files([path], append=True)
            if play:
                window.playlist.set_current(len(window.playlist.items) - 1)

    def plugin_playlist_remove(self, index: int) -> None:
        self.window.playlist.remove(int(index))

    def plugin_playlist_play(self, index: int) -> None:
        self.window.playlist.set_current(int(index))

    def shutdown(self) -> None:
        self.manager.shutdown()
        for label in self.overlay_widgets.values():
            label.deleteLater()
        self.overlay_widgets.clear()

    def _error(self, plugin_id: str, message: str) -> None:
        self.osd.show_message(f"Plugin {plugin_id}: {message}", "error")
