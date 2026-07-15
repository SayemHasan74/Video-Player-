"""Completion coverage for auxiliary windows and expanded plugin APIs."""

from __future__ import annotations

import json
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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidget, QTabWidget, QWidget

from config.settings import SettingsStore
from core.filter_store import FilterStore
from core.history_manager import HistoryManager
from core.plugin_manager import PluginManager
from plugin_cli import build_plugin, create_plugin, plugin_manifest
from ui.auxiliary_windows import HistoryWindow, InspectorWindow, WelcomeWindow
from ui.filter_window import FiltersWindow, PRESETS
from ui.plugin_window import PluginWindow
from utils.thumbnail import cached_thumbnails


APP = QApplication.instance() or QApplication([])


class _Player:
    mpv = object()

    def __init__(self) -> None:
        self.properties = {"pause": False}

    def play_pause(self) -> None: pass
    def set_paused(self, value: bool) -> None: self.properties["pause"] = value
    def seek_absolute(self, value: float) -> None: self.properties["time-pos"] = value
    def get_property(self, name: str, default=None): return self.properties.get(name, default)
    def set_property(self, name: str, value) -> None: self.properties[name] = value


class _PluginHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.player = _Player()
        self.osd = SimpleNamespace(show_message=lambda *_args, **_kwargs: None)

    def plugin_player_status(self): return {"paused": False}
    def plugin_playlist_items(self): return []
    def plugin_playlist_add(self, source, play=False): pass
    def plugin_playlist_remove(self, index): pass
    def plugin_playlist_play(self, index): pass


class ExistingWindowsPluginTests(unittest.TestCase):
    def test_filter_presets_parameters_and_long_rows_are_complete(self) -> None:
        expected = {"crop", "expand", "sharpen", "blur", "delogo", "negative", "vflip", "hflip", "lut3d", "custom mpv", "custom lavfi"}
        self.assertEqual(set(PRESETS), expected)
        self.assertEqual([name for name, *_rest in PRESETS["crop"]], ["w", "h", "x", "y"])
        self.assertEqual([name for name, *_rest in PRESETS["expand"]], ["w", "h", "x", "y", "aspect", "round"])
        with TemporaryDirectory() as directory:
            window = FiltersWindow(store=FilterStore(Path(directory) / "filters.json"))
            self.assertEqual(window.active.textElideMode(), Qt.TextElideMode.ElideNone)
            self.assertEqual(window.saved.textElideMode(), Qt.TextElideMode.ElideNone)
            window.preset.setCurrentText("sharpen")
            self.assertEqual(window._value(), "lavfi=[unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.1]")
            window.close()

    def test_cached_thumbnail_lookup_validates_source_identity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "movie.mkv"; media.write_bytes(b"media")
            cache = root / "thumbnails" / "entry"; cache.mkdir(parents=True)
            image = cache / "050.jpg"; image.write_bytes(b"\xff\xd8ok\xff\xd9")
            stat = media.stat()
            (cache / "manifest.json").write_text(json.dumps({
                "source": str(media.resolve()), "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "generated": [image.name],
            }), encoding="utf-8")
            with patch("utils.thumbnail.app_data_dir", return_value=root):
                self.assertEqual(cached_thumbnails([str(media)])[str(media)], str(image))

    def test_welcome_is_one_drop_surface_and_history_respects_reduced_motion(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsStore(root / "settings.json"); settings.load()
            settings.set("ui.animations", False)
            history = HistoryManager(root / "history.sqlite3")
            welcome = WelcomeWindow(history, settings=settings)
            self.assertTrue(all(widget.acceptDrops() for widget in welcome.findChildren(QWidget)))
            history_window = HistoryWindow(history, settings=settings)
            history_window.refresh()
            self.assertEqual(history_window._opacity.opacity(), 1.0)
            welcome.close(); history_window.close(); history.close()

    def test_inspector_exposes_full_track_flags_and_live_status(self) -> None:
        probe = {
            "format": {"format_name": "matroska", "duration": "120"},
            "streams": [{
                "index": 0, "codec_type": "video", "codec_name": "h264",
                "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
                "disposition": {"default": 1, "forced": 0}, "tags": {"language": "eng"},
            }],
            "chapters": [],
        }
        with patch("ui.auxiliary_windows.probe_media", return_value=probe):
            inspector = InspectorWindow(_Player(), "missing.mkv")
        track_tables = inspector.findChildren(QTableWidget)
        self.assertEqual(track_tables[0].columnCount(), 8)
        self.assertEqual(track_tables[0].item(0, 5).text(), "Yes")
        inspector.timer.stop(); inspector.close()

    def test_expanded_plugin_apis_are_owned_sandboxed_and_fault_isolated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); plugins = root / "plugins"; data = root / "data"
            folder = plugins / "sample"; folder.mkdir(parents=True)
            (folder / "plugin.json").write_text(json.dumps({
                "id": "sample.plugin", "name": "Sample", "entry": "main.py",
            }), encoding="utf-8")
            (folder / "main.py").write_text(
                "def setup(api):\n"
                "    api.preferences.define([{'key':'enabled','label':'Enabled','type':'check','default':True}])\n"
                "    api.files.write_text('state/value.txt', 'ready')\n"
                "    api.overlay.show('<b>Overlay</b>', item_id='status', position='top-right')\n"
                "    api.input.register(lambda event: event.get('key') == 65, priority=20)\n"
                "    api.logging.info('loaded')\n",
                encoding="utf-8",
            )
            manager = PluginManager(_PluginHost(), plugins, data)
            manager.discover(); self.assertTrue(manager.set_enabled("sample.plugin", True))
            record = manager.records["sample.plugin"]
            self.assertEqual(record.preference_schema[0]["key"], "enabled")
            self.assertEqual((data / "sample.plugin" / "files" / "state" / "value.txt").read_text(), "ready")
            self.assertEqual(manager.overlay_items()[0].position, "top-right")
            self.assertTrue(manager.dispatch_input({"key": 65}, "before"))
            self.assertIn("loaded", manager.logs[-1].message)
            with self.assertRaises(ValueError): record.module.api.files.write_text("../escape.txt", "bad")
            result = record.module.api.process.run(sys.executable, ["-c", "print('safe')"])
            self.assertEqual(result["returncode"], 0)
            self.assertIn("safe", result["stdout"])
            record.module.api.input.register(lambda _event: 1 / 0, priority=100)
            self.assertTrue(manager.dispatch_input({"key": 65}, "before"))
            self.assertIn("division", record.error)
            viewer = PluginWindow(manager)
            self.assertEqual(viewer.findChild(QTabWidget).count(), 3)
            self.assertIn("loaded", viewer.logs.toPlainText())
            viewer.close()
            manager.shutdown()

    def test_user_scripts_and_scaffolding_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = PluginManager(_PluginHost(), root / "plugins", root / "data")
            manager.save_user_script("Quick", "api.files.write_text('ran.txt', 'yes')\napi.logging.info('ran')\n")
            self.assertTrue(manager.run_user_script("Quick"))
            self.assertTrue((root / "data" / "user-script.Quick" / "files" / "ran.txt").exists())
            scaffold = create_plugin("Demo", "demo.plugin", root / "scaffolds")
            self.assertEqual(plugin_manifest(scaffold)["id"], "demo.plugin")
            self.assertTrue(build_plugin(scaffold).exists())
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
