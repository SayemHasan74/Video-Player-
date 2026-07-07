"""Audio/subtitle track menu helpers."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMenu, QWidget

from config.settings import SUBTITLE_EXTENSIONS


class TrackMenuFactory:
    """Create mpv track menus."""

    def __init__(self, parent: QWidget) -> None:
        self.parent = parent

    def subtitle_menu(self, tracks: list[dict]) -> QMenu:
        menu = QMenu(self.parent)
        off = menu.addAction("Subtitle Off")
        off.setData("no")
        if tracks:
            menu.addSeparator()
        for track in tracks:
            title = self._track_title(track)
            action = menu.addAction(title)
            action.setData(track.get("id"))
            action.setCheckable(True)
            action.setChecked(bool(track.get("selected")))
        menu.addSeparator()
        load = menu.addAction("Load external...")
        load.setData("__load_external__")
        return menu

    def audio_menu(self, tracks: list[dict]) -> QMenu:
        menu = QMenu(self.parent)
        for track in tracks:
            action = menu.addAction(self._track_title(track))
            action.setData(track.get("id"))
            action.setCheckable(True)
            action.setChecked(bool(track.get("selected")))
        return menu

    def choose_subtitle_file(self) -> str:
        filters = "Subtitle files (" + " ".join(f"*{ext}" for ext in sorted(SUBTITLE_EXTENSIONS)) + ")"
        path, _ = QFileDialog.getOpenFileName(self.parent, "Load Subtitle", str(Path.home()), filters)
        return path

    def _track_title(self, track: dict) -> str:
        language = track.get("lang") or "und"
        title = track.get("title") or track.get("external-filename") or ""
        label = f"{track.get('id')} - {language}"
        return f"{label} - {title}" if title else label
