"""Regression coverage for scoped input and advanced playlist behavior."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "prism_player"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication

from core.playlist_manager import PlaylistItem, PlaylistManager
from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from ui.main_window import MainWindow
from ui.media_open_controller import MediaOpenController
from ui.playlist_panel import PlaylistPanel
from utils.file_utils import expand_input_paths, parse_m3u, resolve_bdmv_main_title


APP = QApplication.instance() or QApplication([])


class _Settings:
    def get(self, key: str, fallback=None):
        return {"playback.open_behavior": "replace"}.get(key, fallback)

    def set(self, *_args) -> None:
        pass


class _OpenHost(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.settings = _Settings()
        self.playlist = PlaylistManager(self)
        self.player = SimpleNamespace(is_loaded=False)
        self.messages: list[str] = []
        self.osd = SimpleNamespace(show_message=lambda message, *_args, **_kwargs: self.messages.append(message))


class PlaylistInputAndModeTests(unittest.TestCase):
    def test_m3u_parses_relative_entries_titles_and_urls(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "Season" / "Episode 01.mkv"
            media.parent.mkdir(); media.touch()
            playlist = root / "show.m3u8"
            playlist.write_text(
                "#EXTM3U\n#EXTINF:120,The Pilot\nSeason/Episode 01.mkv\nhttps://example.com/live\n",
                encoding="utf-8",
            )
            entries = parse_m3u(playlist)
            self.assertEqual(entries[0].source, str(media.resolve()))
            self.assertEqual(entries[0].title, "The Pilot")
            self.assertTrue(entries[0].title_explicit)
            self.assertFalse(entries[0].autoload_subtitles)
            self.assertEqual(entries[1].source, "https://example.com/live")

    def test_explicit_playlist_never_adds_sibling_media(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            listed = root / "listed.mkv"; listed.touch()
            (root / "unrelated.mkv").touch()
            (root / "listed.srt").touch()
            m3u = root / "only.m3u"; m3u.write_text("listed.mkv\n", encoding="utf-8")
            host = _OpenHost(); controller = MediaOpenController(host)
            controller.open_files([m3u], append=False)
            self.assertEqual([item.source for item in host.playlist.items], [str(listed.resolve())])
            self.assertFalse(host.playlist.items[0].autoload_subtitles)

    def test_loose_file_still_builds_sibling_queue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.mkv"; first.touch()
            second = root / "b.mp4"; second.touch()
            host = _OpenHost(); controller = MediaOpenController(host)
            controller.open_files([second], append=False)
            self.assertEqual({Path(item.source).name for item in host.playlist.items}, {"a.mkv", "b.mp4"})
            self.assertEqual(Path(host.playlist.current_item().source).name, "b.mp4")

    def test_folder_is_recursive_and_bdmv_is_one_main_title(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"; nested.mkdir(); (nested / "song.flac").touch()
            stream = root / "disc" / "BDMV" / "STREAM"; stream.mkdir(parents=True)
            short = stream / "00001.m2ts"; short.write_bytes(b"1")
            main = stream / "00002.m2ts"; main.write_bytes(b"1" * 30)
            entries, explicit = expand_input_paths([root], recursive_folders=True)
            self.assertFalse(explicit)
            self.assertEqual({Path(entry.source).name for entry in entries}, {"song.flac", "00002.m2ts"})
            self.assertEqual(resolve_bdmv_main_title(root / "disc"), main)

    def test_repeat_modes_are_independent_and_batch_move_preserves_current(self) -> None:
        manager = PlaylistManager()
        manager.add_sources(["a.mkv", "b.mkv", "c.mkv", "d.mkv"])
        manager.set_current(1)
        current = manager.current_item()
        manager.set_repeat_one(True); manager.set_repeat_all(True); manager.set_shuffle(True)
        self.assertTrue(manager.repeat_one and manager.repeat_all and manager.shuffle)
        self.assertIs(manager.next(), current)
        manager.move_many([0, 2], 4)
        self.assertIs(manager.current_item(), current)
        self.assertEqual([item.title for item in manager.items], ["b.mkv", "d.mkv", "a.mkv", "c.mkv"])

    def test_panel_common_path_footer_chapter_and_local_delete_guard(self) -> None:
        panel = PlaylistPanel()
        items = [
            PlaylistItem("C:/Shows/Mentalist/Season 01/Episode 01 Pilot.mkv", "Episode 01 Pilot", duration=120),
            PlaylistItem("C:/Shows/Mentalist/Season 01/Episode 02 Red Hair.mkv", "Episode 02 Red Hair", duration=180),
        ]
        with patch("ui.playlist_panel.PlaylistProbeWorker.start"):
            panel.refresh(items, 0)
        self.assertTrue(panel.path_prefix.isVisibleTo(panel))
        self.assertEqual(panel.path_prefix.text(), "Path ▸")
        self.assertIn("Mentalist", panel.path_prefix.toolTip())
        self.assertEqual(panel._display_path(items[0]), "")
        self.assertIsNone(panel.list.itemWidget(panel.list.item(0)))
        panel.path_prefix.setChecked(True)
        self.assertEqual(panel.path_prefix.text(), "Path ▾")
        self.assertIn("Season 01", panel._display_path(items[0]))
        panel.list.item(0).setSelected(True); panel.list.item(1).setSelected(True)
        panel._update_footer()
        self.assertIn("selected 2", panel.footer.text())
        self.assertIn("05:00", panel.footer.text())
        panel.set_chapters([{"title": "One", "time": 0}, {"title": "Two", "time": 60}])
        panel.update_current_chapter(90)
        self.assertEqual(panel.chapters.item(1).font().weight(), 600)
        menu, _handlers = panel._build_context_menu(0, [0], items[0].source)
        delete = next(action for action in menu.actions() if action.text() == "Delete Local File(s)…")
        self.assertFalse(delete.isEnabled())
        panel.shutdown(); panel.deleteLater(); APP.processEvents()

    def test_playlist_file_suppresses_automatic_subtitle_loading(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "episode.mkv"; media.touch()
            (root / "episode.srt").touch()
            playlist = root / "show.m3u"; playlist.write_text("episode.mkv\n", encoding="utf-8")
            settings = SettingsStore(root / "settings.json"); settings.load(); settings.set("startup.show_welcome", False)
            history = HistoryManager(root / "history.sqlite3")
            with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
                window = MainWindow(settings, history, [])
            loaded_subtitles: list[object] = []
            window.player.load = lambda *_args: None
            window.player.load_subtitle = lambda path, **_kwargs: loaded_subtitles.append(path)
            with patch("ui.main_window.matching_subtitles", return_value=[root / "episode.srt"]):
                window.open_files([playlist], append=False)
            self.assertEqual(loaded_subtitles, [])
            window.close(); window.deleteLater(); APP.processEvents()


if __name__ == "__main__":
    unittest.main()
