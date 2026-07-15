"""Regression tests for IINA prompt sections 8–17."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prism_player"))

from core.filter_store import FilterStore
from core.history_manager import HistoryManager
from core.keybindings import KeyBindingStore
from core.media_probe import matching_subtitles, probe_media
from core.player_backend import PlayerBackend
from config.settings import SettingsStore
from ui.auxiliary_windows import HistoryWindow, PreferencesWindow, WelcomeWindow
from ui.filter_window import FiltersWindow, PRESETS
from ui.main_window import MainWindow
from ui.quick_settings import QuickSettingsPanel
from ui.seekbar import SeekBar
from ui.title_bar import TitleBar
from utils.thumbnail import adaptive_sample_count, valid_jpeg


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_quick_settings_exposes_complete_reactive_controls(self) -> None:
        panel = QuickSettingsPanel()
        required = {
            "video-aspect-override", "video-rotate", "hwdec", "brightness", "contrast",
            "saturation", "gamma", "hue", "speed", "audio-delay", "volume",
            "sub-delay", "secondary-sub-delay", "sub-font-size", "sub-border-size",
            "sub-shadow-offset", "sub-pos", "sub-codepage",
        }
        self.assertTrue(required.issubset(panel.controls))
        emitted: list[tuple[str, object]] = []
        panel.propertyChanged.connect(lambda name, value: emitted.append((name, value)))
        panel.set_state({"speed": 2.0, "brightness": 15, "video-aspect-override": "no"})
        self.assertEqual(emitted, [])
        self.assertAlmostEqual(panel.speed.spin.value(), 2.0)
        panel.set_crop(640, 360, 10, 20)
        self.assertEqual(emitted[-1], ("crop", {"w": 640, "h": 360, "x": 10, "y": 20}))
        panel.deleteLater()

    def test_seekbar_clicks_map_to_seconds_and_zero_duration_clears_progress(self) -> None:
        bar = SeekBar()
        bar.resize(110, 24)
        bar.set_duration(100)
        bar.show()
        self.app.processEvents()
        previews: list[float] = []
        seeks: list[float] = []
        bar.seekPreviewRequested.connect(previews.append)
        bar.seekRequested.connect(seeks.append)
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(80, 12))
        self.assertEqual(len(previews), 1)
        self.assertEqual(len(seeks), 1)
        self.assertAlmostEqual(seeks[-1], 75.0, delta=0.2)
        self.assertEqual(bar.value(), 750)
        bar.set_duration(0)
        self.assertEqual(bar.value(), 0)
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(100, 12))
        self.assertEqual(bar.value(), 0)
        bar.close()

    def test_new_load_resets_timeline_and_exact_seek_reaches_mpv(self) -> None:
        class FakeMpv:
            def __init__(self) -> None:
                self.commands: list[tuple] = []

            def command(self, *values: object) -> None:
                self.commands.append(values)

        fake = FakeMpv()
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", fake)):
            backend = PlayerBackend()
        backend._duration = 2600.0
        backend._position = 600.0
        durations: list[float] = []
        positions: list[float] = []
        backend.durationChanged.connect(durations.append)
        backend.timeChanged.connect(positions.append)
        backend.load("next-episode.mkv")
        self.assertEqual(durations, [0.0])
        self.assertEqual(positions, [0.0])
        self.assertEqual((backend._duration, backend._position), (0.0, 0.0))
        backend.seek_absolute(42.5)
        self.assertIn(("seek", 42.5, "absolute+exact"), fake.commands)
        backend.seek_preview(75.0)
        self.assertEqual(fake.commands[-1], ("seek", 75.0, "absolute+keyframes"))
        command_count = len(fake.commands)
        backend._paused = False
        backend.complete_ui_seek(75.0)
        self.assertEqual(len(fake.commands), command_count)
        backend.seek_preview(80.0)
        backend._paused = True
        backend.complete_ui_seek(80.0)
        self.assertEqual(fake.commands[-1], ("seek", 80.0, "absolute+exact"))
        backend.poll_timer.stop()

    def test_playlist_key_has_one_application_shortcut_and_opens_panel(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsStore(root / "settings.json")
            settings.load()
            settings.set("startup.show_welcome", False)
            history = HistoryManager(root / "history.sqlite3")
            with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
                window = MainWindow(settings, history, [])
            window.show()
            window.activateWindow()
            window.setFocus()
            self.app.processEvents()
            duplicate_shortcuts = [
                shortcut for shortcut in window._binding_shortcuts
                if shortcut.key().toString() == "P"
            ]
            self.assertEqual(duplicate_shortcuts, [])
            playlist_action = window._menu_actions["playlist"]
            self.assertEqual(playlist_action.shortcut().toString(), "P")
            self.assertEqual(playlist_action.shortcutContext(), Qt.ShortcutContext.ApplicationShortcut)
            self.assertFalse(window.playlist_panel.isVisible())
            QTest.keyClick(window, Qt.Key.Key_P)
            self.app.processEvents()
            self.assertTrue(window.playlist_panel.isVisible())
            window.close()

    def test_title_bar_paints_an_opaque_background(self) -> None:
        title = TitleBar()
        title.resize(800, 40)
        title.show()
        self.app.processEvents()
        pixel = title.grab().toImage().pixelColor(400, 8)
        self.assertEqual(pixel.alpha(), 255)
        self.assertEqual(pixel.name(), "#0d0d0d")
        title.close()

    def test_filter_store_migrates_old_values_and_round_trips(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "filters.json"
            path.write_text(json.dumps(["hflip"]), encoding="utf-8")
            store = FilterStore(path)
            presets = store.load()
            self.assertEqual(presets[0]["value"], "hflip")
            presets[0].update(name="Mirror", shortcut="Ctrl+H", enabled=True)
            store.save(presets)
            self.assertEqual(store.load()[0]["shortcut"], "Ctrl+H")

    def test_filter_window_has_all_typed_presets(self) -> None:
        with TemporaryDirectory() as directory:
            window = FiltersWindow(store=FilterStore(Path(directory) / "filters.json"))
            self.assertTrue({"crop", "expand", "sharpen", "blur", "delogo", "negative", "vflip", "hflip", "lut3d", "custom mpv", "custom lavfi"}.issubset(PRESETS))
            window.preset.setCurrentText("sharpen")
            self.assertEqual(set(window.parameters), {"amount", "matrix"})
            self.assertIn("unsharp", window._value())
            window.close()

    def test_history_background_writer_is_visible_to_reads(self) -> None:
        with TemporaryDirectory() as directory:
            manager = HistoryManager(Path(directory) / "history.sqlite3")
            manager.save_position("movie.mkv", "Movie", 45, 120)
            self.assertTrue(manager.flush())
            self.assertEqual(manager.entries()[0]["source"], "movie.mkv")
            self.assertEqual(manager.resume_position("movie.mkv"), 45)
            manager.remove("movie.mkv")
            manager.flush()
            self.assertEqual(manager.entries(), [])
            manager.close()

    def test_welcome_and_history_accept_real_file_icons(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "movie.mkv"
            media.touch()
            manager = HistoryManager(root / "history.sqlite3")
            manager.save_position(str(media), "Movie", 45, 120)
            self.assertTrue(manager.flush())
            welcome = WelcomeWindow(manager)
            history = HistoryWindow(manager)
            self.assertEqual(welcome.recent.count(), 1)
            self.assertEqual(history.list.count(), 1)
            welcome.close()
            history.close()
            manager.close()

    def test_key_profiles_are_persistent_and_builtins_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            store = KeyBindingStore(Path(directory))
            store.duplicate("Default", "Custom")
            bindings = store.load("Custom")
            bindings["Ctrl+Shift+P"] = "preferences"
            store.save("Custom", bindings)
            self.assertIn("Custom", store.profile_names())
            self.assertEqual(store.load("Custom")["Ctrl+Shift+P"], "preferences")
            with self.assertRaises(ValueError):
                store.save("Default", {})
            store.delete("Custom")
            self.assertNotIn("Custom", store.profile_names())

    def test_preferences_contains_all_searchable_sections(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsStore(root / "settings.json")
            settings.load()
            history = HistoryManager(root / "history.sqlite3")
            window = PreferencesWindow(settings, history)
            names = [window.sections.item(row).text() for row in range(window.sections.count())]
            self.assertEqual(names, ["General", "UI", "Video/Codec", "Audio", "Subtitle", "Network", "Key Bindings", "Advanced", "Utilities"])
            window._filter("proxy")
            visible = [window.sections.item(row).text() for row in range(window.sections.count()) if not window.sections.item(row).isHidden()]
            self.assertEqual(visible, ["Network"])
            window.close()
            history.close()

    def test_thumbnail_validation_and_long_media_sampling(self) -> None:
        self.assertEqual(adaptive_sample_count(3600, 100), 100)
        self.assertEqual(adaptive_sample_count(7 * 3600, 100), 50)
        with TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"\xff\xd8body\xff\xd9")
            self.assertTrue(valid_jpeg(image))
            image.write_bytes(b"broken")
            self.assertFalse(valid_jpeg(image))

    def test_subtitle_matching_handles_language_suffixes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "Example.Show.S01E01.mkv"
            subtitle = root / "Example Show S01E01.en.srt"
            unrelated = root / "Another.Movie.srt"
            media.touch(); subtitle.touch(); unrelated.touch()
            self.assertEqual(matching_subtitles(str(media)), [subtitle])

    def test_media_probe_decodes_ffprobe_json_as_utf8_on_windows(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "Stairway ⭐️.mp3"
            media.touch()
            payload = json.dumps(
                {"format": {"tags": {"title": "Stairway ⭐️"}}},
                ensure_ascii=False,
            ).encode("utf-8")
            probe_media.cache_clear()
            with patch("core.media_probe.shutil.which", return_value="ffprobe"), patch(
                "core.media_probe.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=payload),
            ):
                result = probe_media(str(media))
            self.assertEqual(result["format"]["tags"]["title"], "Stairway ⭐️")
            probe_media.cache_clear()

    def test_media_probe_treats_missing_subprocess_output_as_a_cache_miss(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "broken.mp3"
            media.touch()
            probe_media.cache_clear()
            with patch("core.media_probe.shutil.which", return_value="ffprobe"), patch(
                "core.media_probe.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=None),
            ):
                self.assertEqual(probe_media(str(media)), {})
            probe_media.cache_clear()


if __name__ == "__main__":
    unittest.main()
