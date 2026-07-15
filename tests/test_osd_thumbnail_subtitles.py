"""Regression coverage for prompt OSD/buffering/thumbnail/subtitle hardening."""

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
sys.path.insert(0, str(PACKAGE))

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

from config.settings import SettingsStore
from core.player_backend import PlayerBackend
from ui.input_controller import PlayerInputController
from ui.osd import BufferingIndicator, OSDLabel
from utils.thumbnail import (
    build_ffmpeg_batch_command,
    expected_manifest,
    probe_rotation,
    validate_thumbnail_manifest,
)


APP = QApplication.instance() or QApplication([])


class OsdThumbnailSubtitleTests(unittest.TestCase):
    def test_osd_category_suppression_position_and_escape_dismissal(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            settings.load()
            parent = QWidget()
            parent.resize(640, 400)
            parent.show()
            APP.processEvents()
            osd = OSDLabel(parent, settings)
            settings.set("ui.osd_suppressed_categories", "volume, filters")
            self.assertFalse(osd.show_message("Volume", category="volume"))
            self.assertFalse(osd.isVisible())
            settings.set("ui.osd_suppressed_categories", "")
            settings.set("ui.osd_position", "bottom")
            self.assertTrue(osd.show_message("Searching…", duration=0, category="subtitles"))
            self.assertGreater(osd.y(), parent.height() // 2)

            calls: list[str] = []
            class FakeWindow(QObject):
                def __init__(self) -> None:
                    super().__init__()
                    self.osd = osd

                def _pause_and_minimize(self) -> None:
                    calls.append("minimize")

            window = FakeWindow()
            controller = PlayerInputController(window)
            controller.handle_key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.assertFalse(osd.isVisible())
            self.assertEqual(calls, [])
            parent.close()

    def test_buffering_spinner_respects_reduced_motion_and_mode(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            settings.load()
            parent = QWidget()
            parent.show()
            APP.processEvents()
            with patch("ui.osd.transitions_enabled", return_value=False):
                indicator = BufferingIndicator(settings, parent)
                indicator.set_active(True)
                self.assertTrue(indicator.isVisible())
                self.assertFalse(indicator.spinner.timer.isActive())
            settings.set("ui.buffering_throbber", "off")
            indicator.apply_preferences()
            self.assertFalse(indicator.isVisible())
            parent.close()

    def test_manifest_validation_rotation_and_batched_input_seeks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rotated.mp4"
            source.write_bytes(b"media")
            expected = expected_manifest(source, 120.0, 10, 270)
            manifest = root / "manifest.json"
            manifest.write_text("{broken", encoding="utf-8")
            self.assertIsNone(validate_thumbnail_manifest(manifest, expected))
            payload = {**expected, "complete": False, "generated": ["000.jpg"]}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate_thumbnail_manifest(manifest, expected), payload)

            with patch("utils.thumbnail.probe_media", return_value={
                "streams": [{"codec_type": "video", "side_data_list": [{"rotation": -90}]}]
            }):
                self.assertEqual(probe_rotation(source), 270)
            command = build_ffmpeg_batch_command(
                "ffmpeg", str(source), [(1.0, root / "a.jpg"), (9.0, root / "b.jpg")]
            )
            self.assertEqual(command.count("-ss"), 2)
            self.assertEqual(command.count("-autorotate"), 2)
            self.assertIn("0:v:0", command)
            self.assertIn("1:v:0", command)

    def test_external_subtitle_selection_is_explicit_and_dual_safe(self) -> None:
        class FakeMpv:
            def __init__(self) -> None:
                self.commands: list[tuple] = []
                self.next_track = 7
                self.sid: object = "no"
                self.secondary_sid: object = "no"
                self.pause = True
                self.volume = 80
                self.mute = False
                self.speed = 1.0
                self.panscan = 0.0

            def command(self, *values: object) -> object:
                self.commands.append(values)
                if values and values[0] == "sub-add":
                    result = self.next_track
                    self.next_track += 1
                    return result
                return None

            def _get_property(self, name: str) -> object:
                return getattr(self, name.replace("-", "_"), None)

        fake = FakeMpv()
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", fake)):
            backend = PlayerBackend()
        backend.is_loaded = True
        self.assertEqual(backend.load_subtitle(Path("primary.srt")), 7)
        self.assertEqual(fake.sid, 7)
        self.assertEqual(backend.load_subtitle(Path("secondary.srt"), select=False, secondary=True), 8)
        self.assertEqual(fake.sid, 7)
        self.assertEqual(fake.secondary_sid, 8)
        backend.configure_subtitles(exclude_embedded_auto=True)
        backend.load("movie.mkv")
        self.assertEqual(fake.sid, "no")
        backend.poll_timer.stop()

    def test_buffering_comes_from_mpv_and_excludes_seek_state(self) -> None:
        class FakeMpv:
            time_pos = 1.0
            duration = 100.0
            pause = False
            paused_for_cache = True
            track_list: list[dict] = []

            def __init__(self) -> None:
                self.seeking = True

            def _get_property(self, name: str) -> object:
                values = {
                    "paused-for-cache": True,
                    "seeking": self.seeking,
                    "demuxer-cache-state": {},
                    "eof-reached": False,
                    "path": "",
                    "vf": [],
                    "af": [],
                }
                return values.get(name)

        fake = FakeMpv()
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", fake)):
            backend = PlayerBackend()
        backend.is_loaded = True
        changes: list[bool] = []
        backend.bufferingChanged.connect(changes.append)
        backend._poll_state()
        self.assertEqual(changes, [])
        fake.seeking = False
        backend._poll_state()
        self.assertEqual(changes, [True])
        backend.poll_timer.stop()


if __name__ == "__main__":
    unittest.main()
