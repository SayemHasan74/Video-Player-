"""Regression coverage for preferences, commands and multi-window policies."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "prism_player"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.keybindings import BUILTIN_PROFILES, KeyBindingStore
from core.history_manager import HistoryManager
from core.playlist_manager import PlaylistItem, PlaylistManager
from ui.action_registry import ActionRegistry
from ui.media_open_controller import MediaOpenController
from ui.auxiliary_windows import WelcomeWindow


APP = QApplication.instance() or QApplication([])


class _WindowHost(QObject):
    def __init__(self, settings: SettingsStore) -> None:
        super().__init__()
        self.settings = settings
        self.playlist = PlaylistManager(self)
        self.player = SimpleNamespace(is_loaded=False)
        self.osd = SimpleNamespace(show_message=lambda *_args, **_kwargs: None)
        self.window_manager = SimpleNamespace(open_paths_calls=[])
        self.window_manager.open_paths = lambda paths: self.window_manager.open_paths_calls.append(paths)


class PreferencesActionsOpeningTests(unittest.TestCase):
    def test_old_open_behavior_migrates_to_both_granular_preferences(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"playback": {"open_behavior": "append"}}), encoding="utf-8")
            settings = SettingsStore(path)
            settings.load()
            self.assertEqual(settings.get("playback.open_single_behavior"), "append")
            self.assertEqual(settings.get("playback.open_multiple_behavior"), "append")

    def test_iina_mpv_vlc_profiles_and_custom_rename(self) -> None:
        self.assertTrue({"IINA-style", "mpv-style", "VLC-style"}.issubset(BUILTIN_PROFILES))
        self.assertEqual(BUILTIN_PROFILES["IINA-style"]["P"], "playlist")
        with TemporaryDirectory() as directory:
            store = KeyBindingStore(Path(directory))
            store.duplicate("IINA-style", "Personal")
            store.rename("Personal", "Personal 2")
            self.assertNotIn("Personal", store.profile_names())
            self.assertIn("Personal 2", store.profile_names())

    def test_action_registry_reuses_one_callback_for_qaction_and_direct_trigger(self) -> None:
        calls: list[str] = []
        registry = ActionRegistry()
        registry.register("playlist", "Playlist", lambda: calls.append("playlist"))
        action = registry.qaction("playlist", registry)
        action.trigger()
        registry.trigger("playlist")
        self.assertEqual(calls, ["playlist", "playlist"])
        self.assertIs(action, registry.qaction("playlist", registry))

    def test_open_policies_and_modifier_overrides_are_shared(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            settings.load()
            settings.set("playback.open_single_behavior", "replace")
            settings.set("playback.open_multiple_behavior", "new_window")
            host = _WindowHost(settings)
            controller = MediaOpenController(host)
            self.assertEqual(controller.open_behavior(1), "replace")
            self.assertEqual(controller.open_behavior(2), "new_window")
            self.assertEqual(
                controller.open_behavior(1, Qt.KeyboardModifier.AltModifier), "new_window"
            )
            self.assertEqual(
                controller.open_behavior(2, Qt.KeyboardModifier.AltModifier), "replace"
            )
            self.assertEqual(
                controller.open_behavior(2, Qt.KeyboardModifier.ShiftModifier), "append"
            )

    def test_new_window_policy_keeps_first_file_and_splits_the_rest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / f"{name}.mkv" for name in ("one", "two", "three")]
            for path in files:
                path.touch()
            settings = SettingsStore(root / "settings.json")
            settings.load()
            settings.set("playback.open_multiple_behavior", "new_window")
            host = _WindowHost(settings)
            controller = MediaOpenController(host)
            controller.open_files(files)
            self.assertEqual(Path(host.playlist.current_item().source), files[0])
            self.assertEqual(host.window_manager.open_paths_calls, [[files[1]], [files[2]]])

    def test_playlist_recents_are_recorded_and_only_shown_when_enabled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "episode.mkv"
            media.touch()
            playlist = root / "season.m3u8"
            playlist.write_text("episode.mkv\n", encoding="utf-8")
            settings = SettingsStore(root / "settings.json")
            settings.load()
            host = _WindowHost(settings)
            MediaOpenController(host).open_files([playlist], append=False)
            self.assertEqual(settings.get("startup.playlist_recents"), [str(playlist.resolve())])
            history = HistoryManager(root / "history.sqlite3")
            hidden = WelcomeWindow(history, settings=settings)
            self.assertEqual(hidden.recent.count(), 0)
            hidden.close()
            settings.set("startup.show_playlist_recents", True)
            shown = WelcomeWindow(history, settings=settings)
            self.assertEqual(shown.recent.count(), 1)
            self.assertEqual(shown.recent.item(0).data(Qt.ItemDataRole.UserRole), str(playlist.resolve()))
            shown.close()
            history.close()


if __name__ == "__main__":
    unittest.main()
