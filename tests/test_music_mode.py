"""Acceptance coverage for the complete shared-session Music Mode."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "prism_player"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from PyQt6.QtCore import QEventLoop, QRect, QTimer, Qt, QUrl
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.cover_art import extract_cover_art
from core.player_backend import PlayerBackend
from core.playlist_manager import PlaylistItem
from ui.main_window import MainWindow
from ui.music_mode import MusicModeController, MusicModeView
from ui.playlist_panel import PlaylistPanel
from ui.window_mode import WindowMode


APP = QApplication.instance() or QApplication([])


class MusicModeTests(unittest.TestCase):
    @staticmethod
    def _dispose(widget: object) -> None:
        widget.close()
        widget.deleteLater()
        APP.processEvents()

    def _window(self, root: Path, show_playlist: bool = False) -> MainWindow:
        settings = SettingsStore(root / "settings.json")
        settings.load()
        settings.set("startup.show_welcome", False)
        settings.set("music_mode.show_playlist", show_playlist)
        settings.set("ui.show_playlist", show_playlist)
        history = HistoryManager(root / "history.sqlite3")
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
            window = MainWindow(settings, history, [])
        window.show()
        APP.processEvents()
        return window

    def test_music_mode_reparents_shared_views_without_reloading_and_restores_exactly(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), show_playlist=True)
            original_geometry = QRect(window.geometry())
            original_player = window.player
            with patch.object(window.player, "load") as load:
                window._toggle_mini_mode()
                APP.processEvents()
                self.assertEqual(window.window_modes.mode, WindowMode.COMPACT)
                self.assertIs(window.player, original_player)
                self.assertIs(window.video.parentWidget(), window.music_mode.view.art_host)
                self.assertIs(window.playlist_panel.parentWidget(), window.music_mode.view.playlist_host)
                self.assertTrue(window.music_mode.view.isVisible())
                self.assertTrue(window.playlist_panel.isVisible())
                self.assertFalse(window.title_bar.isVisible())
                self.assertFalse(window.control_bar.isVisible())
                window._toggle_mini_mode()
                APP.processEvents()
                load.assert_not_called()
            self.assertEqual(window.window_modes.mode, WindowMode.NORMAL)
            self.assertEqual(window.geometry(), original_geometry)
            self.assertIs(window.video.parentWidget(), window.central_shell)
            self.assertIs(window.playlist_panel.parentWidget(), window.central_shell)
            self.assertTrue(window.playlist_panel.isVisible())
            self._dispose(window)

    def test_audio_stream_detection_auto_switches_but_manual_exit_wins_for_session(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            window.player.current_source = "audio-in-matroska.mkv"
            info = {
                "source": window.player.current_source,
                "has_audio": True,
                "has_video": False,
                "has_album_art": True,
                "title": "Track",
                "artist": "Artist",
                "album": "Album",
            }
            window.music_mode.media_info_changed(info)
            APP.processEvents()
            self.assertTrue(window._mini_mode)
            self.assertIsNone(window.session.music_mode_manual_override)
            window._toggle_mini_mode()
            APP.processEvents()
            self.assertFalse(window._mini_mode)
            self.assertIs(window.session.music_mode_manual_override, False)
            window.music_mode.media_info_changed(info)
            APP.processEvents()
            self.assertFalse(window._mini_mode)
            self._dispose(window)

    def test_dsd_family_is_recognized_and_view_exposes_complete_audio_layout(self) -> None:
        self.assertTrue(MusicModeController.is_audio_extension("recording.dsf"))
        self.assertTrue(MusicModeController.is_audio_extension("recording.dff"))
        self.assertTrue(MusicModeController.is_audio_extension("recording.dsd"))
        view = MusicModeView(animations_enabled=True)
        view.set_metadata("Title", "Artist", "Album")
        self.assertEqual(view.title_label.text(), "Title")
        self.assertEqual(view.artist_label.text(), "Artist")
        self.assertEqual(view.album_label.text(), "Album")
        self.assertIsNotNone(view.seekbar)
        self.assertIsNotNone(view.previous_button)
        self.assertIsNotNone(view.play_button)
        self.assertIsNotNone(view.next_button)
        self.assertIsNotNone(view.volume)
        view._animate_controls(0.16)
        self.assertEqual(view._controls_animation.duration(), 200)
        view.stop_animation()
        self._dispose(view)

    def test_drop_uses_qt6_modifiers_api_and_routes_file(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            source = Path(directory) / "drop.mp3"
            source.write_bytes(b"not media data")

            class Mime:
                @staticmethod
                def urls() -> list[QUrl]:
                    return [QUrl.fromLocalFile(str(source))]

                @staticmethod
                def hasText() -> bool:
                    return False

            class Drop:
                accepted = False

                @staticmethod
                def mimeData() -> Mime:
                    return Mime()

                @staticmethod
                def modifiers() -> Qt.KeyboardModifier:
                    return Qt.KeyboardModifier.NoModifier

                def acceptProposedAction(self) -> None:
                    self.accepted = True

            drop = Drop()
            with patch.object(window.media_open, "open_files") as opened:
                window.media_open.handle_drop(drop)
            opened.assert_called_once_with([source], append=None)
            self.assertTrue(drop.accepted)
            self._dispose(window)

    def test_cover_art_uses_image_signature_when_id3_mime_is_wrong(self) -> None:
        from mutagen.id3 import APIC, ID3

        with TemporaryDirectory() as directory:
            source = Path(directory) / "tag-only.mp3"
            image = QImage(4, 4, QImage.Format.Format_RGB32)
            image.fill(0xFF336699)
            jpg = Path(directory) / "actual.jpg"
            self.assertTrue(image.save(str(jpg), "JPG"))
            tags = ID3()
            tags.add(APIC(mime="image/png", type=3, desc="Cover", data=jpg.read_bytes()))
            tags.save(source)
            extracted = extract_cover_art(str(source))
            decoded = QImage.fromData(extracted or b"")
            self.assertFalse(decoded.isNull())
            self.assertEqual((decoded.width(), decoded.height()), (4, 4))

    def test_replacing_playlist_does_not_destroy_running_probe_thread(self) -> None:
        import time

        def slow_probe(source: str) -> dict:
            time.sleep(0.04)
            return {"format": {"duration": "1", "tags": {"title": Path(source).name}}}

        panel = PlaylistPanel()
        with patch("ui.playlist_panel.probe_media", side_effect=slow_probe):
            panel.refresh([PlaylistItem("first.mp3", "first")], 0)
            panel.refresh([PlaylistItem("second.mp3", "second")], 0)
            loop = QEventLoop()
            QTimer.singleShot(250, loop.quit)
            loop.exec()
        self.assertFalse(any(worker.isRunning() for worker in panel._probe_workers))
        panel.shutdown()
        self._dispose(panel)

    def test_collapsible_strip_and_expandable_shared_playlist_have_distinct_sizes(self) -> None:
        view = MusicModeView(animations_enabled=False)
        base_height = view.preferred_height()
        view.set_playlist_expanded(True)
        self.assertGreater(view.preferred_height(), base_height)
        view.set_collapsed(True)
        self.assertEqual(view.preferred_height(), MusicModeView.COLLAPSED_HEIGHT)
        view.set_collapsed(False)
        self.assertGreater(view.preferred_height(), base_height)
        self._dispose(view)


if __name__ == "__main__":
    unittest.main()
