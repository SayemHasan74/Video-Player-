"""All media-opening entry points and new-window policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog

from core.playlist_manager import PlaylistItem
from core.url_resolver import UrlResolverWorker
from ui.open_url_dialog import OpenUrlDialog
from utils.file_utils import InputEntry, expand_input_paths, is_playlist_file, is_probable_url, resolve_bdmv_main_title, scan_media_files


class InputScanWorker(QThread):
    scanned = pyqtSignal(list, bool)

    def __init__(self, paths: list[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.paths = paths

    def run(self) -> None:
        entries, explicit_playlist = expand_input_paths(self.paths, recursive_folders=True)
        self.scanned.emit(entries, explicit_playlist)


class MediaOpenController(QObject):
    """Apply one open policy consistently across dialog, drop, paste and CLI paths."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.url_worker: UrlResolverWorker | None = None
        self._scan_workers: set[InputScanWorker] = set()
        self._pending_url_append = False

    def open_files(
        self,
        files: list[Path],
        append: bool | None = None,
        modifiers: Qt.KeyboardModifier | None = None,
        scan_siblings: bool = True,
    ) -> None:
        paths = [Path(path).expanduser() for path in files]
        if not paths:
            return
        if append is None and self.open_behavior(len(paths), modifiers) == "new_window":
            if self.window.playlist.current_item() is not None:
                self.open_in_new_window(paths, separate=len(paths) > 1)
                return
            if len(paths) > 1:
                # Reuse the empty initial window for the first selection and
                # create one independent player session for each remainder.
                self.open_files([paths[0]], append=False, scan_siblings=False)
                self.open_in_new_window(paths[1:], separate=True)
                return
        # Recursive directory walks are kept off the UI thread. Every other
        # entry point calls this same method, so their scoping rules cannot drift.
        if any(path.is_dir() for path in paths):
            worker = InputScanWorker(paths, self)
            self._scan_workers.add(worker)
            worker.scanned.connect(
                lambda entries, explicit, paths=paths, append=append, modifiers=modifiers, scan_siblings=scan_siblings:
                    self._open_entries(entries, explicit, paths, append, modifiers, scan_siblings)
            )
            worker.finished.connect(lambda worker=worker: self._scan_finished(worker))
            worker.start()
            return
        entries, explicit_playlist = expand_input_paths(paths, recursive_folders=True)
        self._open_entries(entries, explicit_playlist, paths, append, modifiers, scan_siblings)

    def _open_entries(
        self,
        entries: list[InputEntry],
        explicit_playlist: bool,
        original_paths: list[Path],
        append: bool | None,
        modifiers: Qt.KeyboardModifier | None = None,
        scan_siblings: bool = True,
    ) -> None:
        window = self.window
        if not entries:
            window.osd.show_message("No supported media files found", "warning", category="playlist")
            return
        if explicit_playlist:
            self._remember_playlist_files(original_paths)
        if append is None:
            behavior = self.open_behavior(len(original_paths), modifiers)
            if behavior == "new_window" and window.playlist.current_item() is not None:
                self.open_in_new_window(original_paths, separate=len(original_paths) > 1)
                return
            append = behavior == "append" and window.playlist.current_item() is not None

        selected_index = 0
        # Only a loose, ordinary media file scans siblings. Playlist files,
        # folders and BDMV selections are explicitly scoped inputs.
        if (
            not append
            and scan_siblings
            and not explicit_playlist
            and len(original_paths) == 1
            and original_paths[0].is_file()
            and not is_playlist_file(original_paths[0])
            and resolve_bdmv_main_title(original_paths[0]) is None
            and len(entries) == 1
        ):
            selected = Path(entries[0].source).resolve()
            siblings = scan_media_files([selected.parent], recursive=False)
            if siblings:
                entries = [InputEntry(str(path), path.name, True) for path in siblings]
                selected_index = next(
                    (index for index, entry in enumerate(entries) if Path(entry.source).resolve() == selected),
                    0,
                )

        models = [
            PlaylistItem(
                source=entry.source,
                title=entry.title or entry.source,
                is_url=is_probable_url(entry.source),
                autoload_subtitles=entry.autoload_subtitles,
                title_explicit=entry.title_explicit,
            )
            for entry in entries
        ]
        window.playlist.add_entries(models, append=bool(append))
        if not append or window.playlist.current_index == -1:
            window.playlist.set_current(selected_index)
        elif not window.player.is_loaded:
            window.playlist.set_current(window.playlist.current_index)

    def open_url(
        self,
        url: str,
        apply_behavior: bool = True,
        modifiers: Qt.KeyboardModifier | None = None,
    ) -> None:
        window = self.window
        behavior = self.open_behavior(1, modifiers) if apply_behavior else "replace"
        if behavior == "new_window" and window.playlist.current_item() is not None:
            self.open_url_in_new_window(url)
            return
        self._pending_url_append = behavior == "append" and window.playlist.current_item() is not None
        window.osd.show_message("Resolving URL...", category="playlist")
        self.url_worker = UrlResolverWorker(
            url,
            str(window.settings.get("network.preferred_format", "bestvideo+bestaudio/best")),
            self,
        )
        self.url_worker.resolved.connect(
            lambda resolved, title: self._play_resolved_url(url, resolved, title)
        )
        self.url_worker.failed.connect(
            lambda error: window.osd.show_message(f"URL failed: {error}", "error", category="playlist")
        )
        self.url_worker.start()

    def show_url_dialog(self, initial_url: str = "") -> None:
        dialog = OpenUrlDialog(initial_url, self.window)
        dialog.urlAccepted.connect(
            lambda url: self.open_url(url, modifiers=QApplication.keyboardModifiers())
        )
        dialog.exec()

    def choose_files(self) -> None:
        window = self.window
        files, _ = QFileDialog.getOpenFileNames(
            window,
            "Open Media or Playlist",
            str(window.settings.get("paths.last_open_dir", Path.home())),
            "Media and playlists (*.m3u *.m3u8);;All files (*)",
        )
        if files:
            window.settings.set("paths.last_open_dir", str(Path(files[0]).parent))
            self.open_files(
                [Path(path) for path in files],
                append=None,
                modifiers=QApplication.keyboardModifiers(),
            )

    def choose_folder(self) -> None:
        window = self.window
        folder = QFileDialog.getExistingDirectory(
            window,
            "Open Folder Recursively",
            str(window.settings.get("paths.last_open_dir", Path.home())),
        )
        if folder:
            window.settings.set("paths.last_open_dir", folder)
            self.open_files(
                [Path(folder)], append=None, modifiers=QApplication.keyboardModifiers()
            )

    def handle_drop(self, event: Any) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        urls = [url.toString() for url in event.mimeData().urls() if not url.isLocalFile()]
        if not urls and event.mimeData().hasText() and is_probable_url(event.mimeData().text()):
            urls.append(event.mimeData().text().strip())
        modifiers = event.modifiers() if hasattr(event, "modifiers") else QApplication.keyboardModifiers()
        if paths:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.open_files(paths, append=True)
            elif modifiers & Qt.KeyboardModifier.AltModifier:
                self.open_files(paths, modifiers=modifiers)
            else:
                self.open_files(paths, append=None)
        if urls:
            self.open_url(
                urls[0],
                modifiers=modifiers if modifiers & Qt.KeyboardModifier.AltModifier else None,
            )
        event.acceptProposedAction()

    def paste_playlist_content(self) -> None:
        mime = QApplication.clipboard().mimeData()
        paths: list[Path] = []
        urls: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    paths.append(Path(url.toLocalFile()))
                elif is_probable_url(url.toString()):
                    urls.append(url.toString())
        if mime.hasText() and not paths and not urls:
            for line in mime.text().splitlines():
                text = line.strip().strip('"')
                if not text:
                    continue
                if is_probable_url(text):
                    urls.append(text)
                else:
                    path = Path(text).expanduser()
                    if path.exists():
                        paths.append(path)
        if paths:
            modifiers = QApplication.keyboardModifiers() & ~Qt.KeyboardModifier.ControlModifier
            self.open_files(paths, append=None, modifiers=modifiers)
        if urls:
            modifiers = QApplication.keyboardModifiers() & ~Qt.KeyboardModifier.ControlModifier
            self.open_url(urls[0], modifiers=modifiers)
        if paths or urls:
            self.window.osd.show_message("Added from clipboard", "success", category="playlist")

    def open_in_new_window(self, paths: list[Path], separate: bool = False) -> None:
        manager = getattr(self.window, "window_manager", None)
        if manager is not None:
            if separate:
                for path in paths:
                    manager.open_paths([path])
            else:
                manager.open_paths(paths)
            return
        path_groups = ([path] for path in paths) if separate else (paths,)
        for group in path_groups:
            command = self._entry_command()
            command.extend(map(str, group))
            self._spawn(command)

    def open_source_in_new_window(self, source: str) -> None:
        if is_probable_url(source):
            self.open_url_in_new_window(source)
        else:
            self.open_in_new_window([Path(source)])

    def open_url_in_new_window(self, url: str) -> None:
        manager = getattr(self.window, "window_manager", None)
        if manager is not None:
            manager.open_url(url)
            return
        command = self._entry_command()
        command.extend(("--url", url))
        self._spawn(command)

    def shutdown(self) -> None:
        workers: list[QThread] = [*self._scan_workers]
        if self.url_worker is not None:
            workers.append(self.url_worker)
        for worker in workers:
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(3000)
        self._scan_workers.clear()

    def _scan_finished(self, worker: InputScanWorker) -> None:
        self._scan_workers.discard(worker)
        worker.deleteLater()

    def _play_resolved_url(self, original_url: str, resolved_url: str, title: str) -> None:
        window = self.window
        item = PlaylistItem(resolved_url, title or original_url, True)
        if not self._pending_url_append:
            window.playlist.clear()
        window.playlist.add_item(item)
        window.playlist.set_current(len(window.playlist.items) - 1)
        self._pending_url_append = False

    def _remember_playlist_files(self, paths: list[Path]) -> None:
        playlist_paths = [str(path.resolve()) for path in paths if is_playlist_file(path)]
        if not playlist_paths:
            return
        existing = self.window.settings.get("startup.playlist_recents", [])
        recents = [str(value) for value in existing] if isinstance(existing, list) else []
        for source in reversed(playlist_paths):
            recents = [value for value in recents if value.casefold() != source.casefold()]
            recents.insert(0, source)
        self.window.settings.set("startup.playlist_recents", recents[:20])
        save = getattr(self.window.settings, "save", None)
        if callable(save):
            save()

    def open_behavior(
        self,
        item_count: int,
        modifiers: Qt.KeyboardModifier | None = None,
    ) -> str:
        """Resolve one policy for every opening entry point.

        Alt temporarily flips between opening here and opening in a new
        window. Shift explicitly queues in the current window. This keeps the
        modifier useful for dialogs, drops, history and the welcome window
        without conflicting with Ctrl-based multi-selection.
        """
        key = "playback.open_single_behavior" if item_count <= 1 else "playback.open_multiple_behavior"
        fallback = str(self.window.settings.get("playback.open_behavior", "replace"))
        behavior = str(self.window.settings.get(key, fallback))
        if behavior not in {"replace", "append", "new_window"}:
            behavior = fallback if fallback in {"replace", "append", "new_window"} else "replace"
        active = modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier
        if active & Qt.KeyboardModifier.ShiftModifier:
            return "append"
        if active & Qt.KeyboardModifier.AltModifier:
            return "replace" if behavior == "new_window" else "new_window"
        return behavior

    @staticmethod
    def _entry_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, str(Path(__file__).resolve().parents[2] / "main.py")]

    @staticmethod
    def _spawn(command: list[str]) -> None:
        creation_flags = 0x00000008 if sys.platform == "win32" else 0
        subprocess.Popen(command, creationflags=creation_flags)
