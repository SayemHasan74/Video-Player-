"""Acceptance coverage for plugin and final behavior work."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "prism_player"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QLabel

from core.media_state_store import MediaStateStore
from core.plugin_manager import PluginManager
from ui.playlist_panel import PlaylistPanel


APP = QApplication.instance() or QApplication([])


class _Player:
    def __init__(self) -> None:
        self.properties: dict[str, object] = {}
        self.seeks: list[float] = []

    def play_pause(self) -> None: pass
    def set_paused(self, _paused: bool) -> None: pass
    def seek_absolute(self, seconds: float) -> None: self.seeks.append(seconds)
    def get_property(self, name: str, fallback=None): return self.properties.get(name, fallback)
    def set_property(self, name: str, value) -> None: self.properties[name] = value


class _Host(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.player = _Player()
        self.osd = SimpleNamespace(show_message=lambda *_args, **_kwargs: None)
        self.played: list[int] = []

    def plugin_player_status(self): return {"paused": False}
    def plugin_playlist_items(self): return [{"index": 0, "source": "movie.mkv"}]
    def plugin_playlist_add(self, source, play=False): pass
    def plugin_playlist_remove(self, index): pass
    def plugin_playlist_play(self, index): self.played.append(index)


class Features1822Tests(unittest.TestCase):
    def _write_plugin(self, root: Path, code: str) -> None:
        folder = root / "sample"
        folder.mkdir()
        (folder / "plugin.json").write_text(json.dumps({
            "id": "sample.plugin", "name": "Sample", "version": "1.2.3",
            "description": "Acceptance plugin", "entry": "main.py",
        }), encoding="utf-8")
        (folder / "main.py").write_text(code, encoding="utf-8")

    def test_plugin_lifecycle_events_preferences_menu_playlist_and_sidebar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); plugins = base / "plugins"; plugins.mkdir(); data = base / "data"
            self._write_plugin(plugins, """
def setup(api):
    api.preferences.set('loads', api.preferences.get('loads', 0) + 1)
    api.events.on('file.loaded', lambda payload: api.preferences.set('last', payload['source']))
    api.menu.add('Say hello', lambda: api.core.osd('hello'))
    api.playlist.add_context_item('Remember row', lambda index, source: api.preferences.set('row', index))
    api.sidebar.register('Sample', lambda: 'Plugin sidebar')
""")
            host = _Host(); manager = PluginManager(host, plugins, data)
            manager.discover()
            self.assertIn("sample.plugin", manager.records)
            self.assertTrue(manager.set_enabled("sample.plugin", True))
            self.assertEqual([item.title for item in manager.menu_items("plugin")], ["Say hello"])
            self.assertEqual([item.title for item in manager.menu_items("playlist_context")], ["Remember row"])
            self.assertEqual(manager.sidebar_items()[0].factory(), "Plugin sidebar")
            manager.events.emit("file.loaded", {"source": "episode.mkv"})
            prefs = json.loads((data / "sample.plugin" / "preferences.json").read_text(encoding="utf-8"))
            self.assertEqual(prefs["loads"], 1)
            self.assertEqual(prefs["last"], "episode.mkv")
            manager.invoke(manager.menu_items("playlist_context")[0], 7, "episode.mkv")
            self.assertEqual(json.loads((data / "sample.plugin" / "preferences.json").read_text())["row"], 7)
            manager.unload("sample.plugin")
            self.assertFalse(manager.menu_items("plugin"))
            self.assertFalse(manager.sidebar_items())
            manager.events.emit("file.loaded", {"source": "ignored.mkv"})
            self.assertEqual(json.loads((data / "sample.plugin" / "preferences.json").read_text())["last"], "episode.mkv")

    def test_bad_plugin_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); plugins = base / "plugins"; plugins.mkdir()
            self._write_plugin(plugins, "def setup(api):\n    raise RuntimeError('boom')\n")
            manager = PluginManager(_Host(), plugins, base / "data")
            manager.discover()
            self.assertFalse(manager.set_enabled("sample.plugin", True))
            self.assertIn("boom", manager.records["sample.plugin"].error)
            self.assertIsNone(manager.records["sample.plugin"].module)
            manager.set_enabled("sample.plugin", False)
            self.assertFalse(manager.records["sample.plugin"].enabled)

    def test_media_visual_state_is_per_file_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = MediaStateStore(path)
            store.update("A.mkv", aspect="16:9", rotation=90, crop={"w": 100, "h": 80, "x": 2, "y": 3})
            store.update("B.mkv", aspect="4:3", rotation=0, crop=None)
            reopened = MediaStateStore(path)
            self.assertEqual(reopened.get("A.mkv")["rotation"], 90)
            self.assertEqual(reopened.get("B.mkv")["aspect"], "4:3")
            self.assertNotEqual(reopened.get("A.mkv"), reopened.get("B.mkv"))

    def test_playlist_accepts_dynamic_plugin_tabs_without_breaking_base_tabs(self) -> None:
        panel = PlaylistPanel()
        panel.add_plugin_tab("sample:one", "Sample", QLabel("Content"))
        self.assertEqual(panel.tabs.count(), 4)
        panel.set_current_tab("plugin:sample:one")
        self.assertEqual(panel.tabs.tabText(panel.tabs.currentIndex()), "Sample")
        panel.clear_plugin_tabs()
        self.assertEqual(panel.tabs.count(), 3)
        self.assertEqual([panel.tabs.tabBar().tabData(i) for i in range(3)], ["playlist", "chapters", "quick_settings"])
        panel.shutdown(); panel.deleteLater()

    def test_final_behavior_hooks_are_wired_without_removing_personal_controls(self) -> None:
        main_source = (PACKAGE / "ui" / "main_window.py").read_text(encoding="utf-8")
        input_source = (PACKAGE / "ui" / "input_controller.py").read_text(encoding="utf-8")
        playback_source = (PACKAGE / "ui" / "playback_event_router.py").read_text(encoding="utf-8")
        media_state_source = (PACKAGE / "ui" / "media_state_controller.py").read_text(encoding="utf-8")
        media_open_source = (PACKAGE / "ui" / "media_open_controller.py").read_text(encoding="utf-8")
        self.assertIn("self.playback_events.connect_all()", main_source)
        self.assertIn("self._connect(control.seekRequested, self.seek_from_ui)", playback_source)
        self.assertIn("window.media_states.update(current.source, rotation=value)", media_state_source)
        self.assertIn("self.open_url_in_new_window(url)", media_open_source)
        self.assertIn("window._note_user_activity()", input_source)
        self.assertIn("window._pause_and_minimize()", input_source)
        self.assertIn("window._toggle_mini_mode()", input_source)
        self.assertIn("window._toggle_playlist()", input_source)


if __name__ == "__main__":
    unittest.main()
