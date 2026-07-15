"""Playlist data structures and navigation."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from utils.file_utils import display_name, is_probable_url


@dataclass
class PlaylistItem:
    """A single playlist entry."""

    source: str
    title: str
    is_url: bool = False
    duration: float = 0.0
    artist: str = ""
    album: str = ""
    has_subtitle: bool = False
    autoload_subtitles: bool = True
    subtitle_paths: list[str] = field(default_factory=list)
    wrong_subtitles: set[str] = field(default_factory=set)
    title_explicit: bool = False

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
        self.repeat_one = False
        self.repeat_all = False
        self.shuffle = False
        self._shuffle_pending: list[int] = []
        self._shuffle_history: list[int] = []

    @property
    def repeat_mode(self) -> str:
        return "one" if self.repeat_one else "all" if self.repeat_all else "none"

    @repeat_mode.setter
    def repeat_mode(self, mode: str) -> None:
        self.repeat_one = mode == "one"
        self.repeat_all = mode == "all"

    def clear(self) -> None:
        """Clear all items."""
        self.items.clear()
        self.current_index = -1
        self.playlistChanged.emit()
        self._reset_shuffle()

    def add_sources(self, sources: list[Path | str], append: bool = True) -> None:
        """Add sources to the playlist."""
        if not append:
            self.items.clear()
            self.current_index = -1
        self.items.extend(PlaylistItem.from_source(source) for source in sources)
        self._reset_shuffle()
        self.playlistChanged.emit()

    def add_entries(self, entries: list[PlaylistItem], append: bool = True) -> None:
        if not append:
            self.items.clear()
            self.current_index = -1
        self.items.extend(entries)
        self._reset_shuffle()
        self.playlistChanged.emit()

    def add_item(self, item: PlaylistItem) -> None:
        """Add an existing item."""
        self.items.append(item)
        self._reset_shuffle()
        self.playlistChanged.emit()

    def remove_many(self, indices: list[int]) -> None:
        selected = sorted({index for index in indices if 0 <= index < len(self.items)})
        if not selected:
            return
        current = self.current_item()
        fallback = min(selected[0], max(0, len(self.items) - len(selected) - 1))
        self.items = [item for index, item in enumerate(self.items) if index not in selected]
        if current in self.items:
            self.current_index = self.items.index(current)
        elif self.items:
            self.current_index = min(fallback, len(self.items) - 1)
            self.currentItemChanged.emit(self.items[self.current_index])
        else:
            self.current_index = -1
        self._reset_shuffle()
        self.playlistChanged.emit()

    def move_many(self, indices: list[int], target_index: int) -> None:
        selected = sorted({index for index in indices if 0 <= index < len(self.items)})
        if not selected:
            return
        current = self.current_item()
        moving = [self.items[index] for index in selected]
        remaining = [item for index, item in enumerate(self.items) if index not in selected]
        removed_before_target = sum(index < target_index for index in selected)
        insert_at = max(0, min(len(remaining), target_index - removed_before_target))
        self.items = remaining[:insert_at] + moving + remaining[insert_at:]
        self.current_index = self.items.index(current) if current in self.items else -1
        self._reset_shuffle()
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
        self._reset_shuffle()

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
        self._reset_shuffle()

    def sort_items(self, mode: str) -> None:
        current = self.current_item(); reverse = mode.endswith("↓")
        key = (lambda item: item.source.casefold()) if mode.startswith("Full path") else (lambda item: item.title.casefold())
        self.items.sort(key=key, reverse=reverse)
        self.current_index = self.items.index(current) if current in self.items else -1
        self.playlistChanged.emit()
        self._reset_shuffle()

    def insert_next(self, item: PlaylistItem) -> None:
        self.items.insert(min(len(self.items), max(0, self.current_index + 1)), item)
        self._reset_shuffle()
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
        if self.shuffle and index in self._shuffle_pending:
            self._shuffle_pending.remove(index)
        return item

    def next(self) -> PlaylistItem | None:
        """Advance to the next item."""
        if not self.items:
            return None
        if self.repeat_one and self.current_index != -1:
            return self.set_current(self.current_index)
        if self.shuffle and len(self.items) > 1:
            if not self._shuffle_pending:
                if not self.repeat_all:
                    return None
                self._reset_shuffle()
            if self.current_index >= 0:
                self._shuffle_history.append(self.current_index)
            return self.set_current(self._shuffle_pending.pop())
        next_index = self.current_index + 1
        if next_index >= len(self.items):
            if self.repeat_all:
                next_index = 0
            else:
                return None
        return self.set_current(next_index)

    def peek_next(self) -> PlaylistItem | None:
        """Return the deterministic successor without mutating playback state."""
        if not self.items or self.shuffle:
            return None
        if self.repeat_one and self.current_index != -1:
            return self.current_item()
        next_index = self.current_index + 1
        if next_index >= len(self.items):
            next_index = 0 if self.repeat_all else -1
        return self.items[next_index] if 0 <= next_index < len(self.items) else None

    def previous(self) -> PlaylistItem | None:
        """Move to the previous item."""
        if not self.items:
            return None
        if self.shuffle and self._shuffle_history:
            return self.set_current(self._shuffle_history.pop())
        previous_index = self.current_index - 1
        if previous_index < 0:
            previous_index = len(self.items) - 1 if self.repeat_all else 0
        return self.set_current(previous_index)

    def set_repeat_one(self, enabled: bool) -> None:
        self.repeat_one = bool(enabled)

    def set_repeat_all(self, enabled: bool) -> None:
        self.repeat_all = bool(enabled)

    def set_shuffle(self, enabled: bool) -> None:
        self.shuffle = bool(enabled)
        self._reset_shuffle()

    def _reset_shuffle(self) -> None:
        self._shuffle_pending = [index for index in range(len(self.items)) if index != self.current_index]
        random.shuffle(self._shuffle_pending)
        self._shuffle_history.clear()
