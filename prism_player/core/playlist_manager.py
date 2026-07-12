"""Playlist data structures and navigation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from utils.file_utils import display_name, is_probable_url


@dataclass
class PlaylistItem:
    """A single playlist entry."""

    source: str
    title: str
    is_url: bool = False

    @classmethod
    def from_source(cls, source: Path | str) -> "PlaylistItem":
        text = str(source)
        return cls(text, display_name(text), is_probable_url(text))


class PlaylistManager(QObject):
    """Manage playlist entries and current selection."""

    playlistChanged = pyqtSignal()
    currentItemChanged = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.items: list[PlaylistItem] = []
        self.current_index = -1
        self.repeat_mode = "none"
        self.shuffle = False

    def clear(self) -> None:
        """Clear all items."""
        self.items.clear()
        self.current_index = -1
        self.playlistChanged.emit()

    def add_sources(self, sources: list[Path | str], append: bool = True) -> None:
        """Add sources to the playlist."""
        if not append:
            self.items.clear()
            self.current_index = -1
        self.items.extend(PlaylistItem.from_source(source) for source in sources)
        self.playlistChanged.emit()

    def add_item(self, item: PlaylistItem) -> None:
        """Add an existing item."""
        self.items.append(item)
        self.playlistChanged.emit()

    def remove(self, index: int) -> None:
        """Remove an item."""
        if not 0 <= index < len(self.items):
            return
        del self.items[index]
        if not self.items:
            self.current_index = -1
        elif index < self.current_index:
            self.current_index -= 1
        elif index == self.current_index:
            self.current_index = min(index, len(self.items) - 1)
            self.currentItemChanged.emit(self.items[self.current_index])
        self.playlistChanged.emit()

    def move(self, source_index: int, target_index: int) -> None:
        """Move an item."""
        if not 0 <= source_index < len(self.items) or not 0 <= target_index < len(self.items):
            return
        item = self.items.pop(source_index)
        self.items.insert(target_index, item)
        if self.current_index == source_index: self.current_index = target_index
        elif source_index < self.current_index <= target_index: self.current_index -= 1
        elif target_index <= self.current_index < source_index: self.current_index += 1
        self.playlistChanged.emit()

    def sort_items(self, mode: str) -> None:
        current = self.current_item(); reverse = mode.endswith("↓")
        key = (lambda item: item.source.casefold()) if mode.startswith("Full path") else (lambda item: item.title.casefold())
        self.items.sort(key=key, reverse=reverse)
        self.current_index = self.items.index(current) if current in self.items else -1
        self.playlistChanged.emit()

    def insert_next(self, item: PlaylistItem) -> None:
        self.items.insert(min(len(self.items), max(0, self.current_index + 1)), item)
        self.playlistChanged.emit()

    def current_item(self) -> PlaylistItem | None:
        """Return the current item."""
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def set_current(self, index: int) -> PlaylistItem | None:
        """Select an index and emit it."""
        if not 0 <= index < len(self.items):
            return None
        self.current_index = index
        item = self.items[index]
        self.currentItemChanged.emit(item)
        self.playlistChanged.emit()
        return item

    def next(self) -> PlaylistItem | None:
        """Advance to the next item."""
        if not self.items:
            return None
        if self.repeat_mode == "one" and self.current_index != -1:
            return self.set_current(self.current_index)
        if self.shuffle and len(self.items) > 1:
            choices = [index for index in range(len(self.items)) if index != self.current_index]
            return self.set_current(random.choice(choices))
        next_index = self.current_index + 1
        if next_index >= len(self.items):
            if self.repeat_mode == "all":
                next_index = 0
            else:
                return None
        return self.set_current(next_index)

    def previous(self) -> PlaylistItem | None:
        """Move to the previous item."""
        if not self.items:
            return None
        previous_index = self.current_index - 1
        if previous_index < 0:
            previous_index = len(self.items) - 1 if self.repeat_mode == "all" else 0
        return self.set_current(previous_index)
