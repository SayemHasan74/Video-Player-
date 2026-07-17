"""Regression coverage for prompt parts 9 and 10."""

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

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.player_backend import PlayerBackend
from core.video_pipeline import VideoPipelineConfig
from integrations.windows_media import WindowsMediaController
from ui.input_controller import PlayerInputController
from ui.mpv_render_window import MpvRenderWindow
from ui.video_widget import VideoWidget
from utils.languages import normalize_language_code, normalize_language_preferences


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class _FakeMpv:
    def __init__(self) -> None:
        self.properties: dict[str, object] = {
            "audio-device-list": [
                {"name": "auto", "description": "Default"},
                {"name": "wasapi/speakers", "description": "Speakers"},
            ],
            "path": "",
            "eof-reached": False,
        }
        self.commands: list[tuple[object, ...]] = []
        self.track_list: list[dict[str, object]] = []
        self.time_pos = 0.0
        self.duration = 180.0
        self.pause = False
        self.paused_for_cache = False

    def _set_property(self, name: str, value: object) -> None:
        self.properties[name] = value

    def _get_property(self, name: str) -> object:
        return self.properties.get(name)

    def command(self, *values: object) -> None:
        self.commands.append(values)


class RendererAudioWindowsTests(unittest.TestCase):
    def _backend(self) -> tuple[PlayerBackend, _FakeMpv]:
        fake = _FakeMpv()
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", fake)):
            backend = PlayerBackend()
        return backend, fake

    def test_true_entrypoint_uses_exact_dll_qt_locale_mpv_order(self) -> None:
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        bootstrap_call = source.index("load_vendored_mpv()")
        self.assertLess(bootstrap_call, source.index("from PyQt6.QtCore import Qt"))
        app_call = source.index("app = QApplication(sys.argv)")
        locale_call = source.index('locale.setlocale(locale.LC_NUMERIC, "C")')
        mpv_call = source.index("import_mpv_module()")
        self.assertLess(app_call, locale_call)
        self.assertLess(locale_call, mpv_call)
        self.assertIn("PassThrough", source[:app_call])
        self.assertNotIn('os.environ["PATH"]', source)
        backend = (PACKAGE / "core/player_backend.py").read_text(encoding="utf-8")
        self.assertNotIn("add_dll_directory", backend)

    def test_video_pipeline_has_safe_sdr_and_explicit_hdr_paths(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json"); settings.load()
            settings.set("video.color_space", "display-p3")
            settings.set("video.hdr_mode", "sdr")
            settings.set("video.tone_mapping", "bt.2390")
            config = VideoPipelineConfig.from_settings(settings)
            props = config.mpv_properties()
            self.assertEqual(props["target-prim"], "display-p3")
            self.assertEqual(props["target-trc"], "srgb")
            self.assertEqual(props["target-colorspace-hint"], "no")
            settings.set("video.hdr_mode", "passthrough")
            props = VideoPipelineConfig.from_settings(settings).mpv_properties()
            self.assertEqual((props["target-prim"], props["target-trc"]), ("bt.2020", "pq"))

        backend, fake = self._backend()
        original_set = backend.set_property

        def reject_hardware(name: str, value: object) -> bool:
            if name == "hwdec" and value != "no":
                return False
            return original_set(name, value)

        backend.set_property = reject_hardware  # type: ignore[method-assign]
        backend.configure_video_pipeline(VideoPipelineConfig(hwdec="auto", hwdec_fallback=True))
        self.assertEqual(fake.properties["hwdec"], "no")
        backend.poll_timer.stop()

    def test_renderer_shutdown_and_physical_framebuffer_sizing_are_explicit(self) -> None:
        render_window = MpvRenderWindow(); render_window.resize(320, 180)
        with patch.object(MpvRenderWindow, "devicePixelRatio", return_value=1.5):
            self.assertEqual(render_window._framebuffer_dimensions(), (480, 270))
        source = (PACKAGE / "ui/mpv_render_window.py").read_text(encoding="utf-8")
        self.assertIn("free_render_context", source)
        self.assertIn("context.swapBuffers(self)", source)
        self.assertIn("report_swap", source)
        render_window.deleteLater()

    def test_replaygain_signed_delay_language_and_device_selection(self) -> None:
        backend, fake = self._backend()
        backend.configure_audio(
            replaygain="album", replaygain_preamp=2.5,
            replaygain_clip=False, replaygain_fallback=-3.0,
            gapless="weak", languages="EN, jpn; und", device="wasapi/speakers",
        )
        self.assertEqual(fake.properties["replaygain"], "album")
        self.assertEqual(fake.properties["replaygain-preamp"], 2.5)
        self.assertEqual(fake.properties["replaygain-clip"], "no")
        self.assertEqual(fake.properties["gapless-audio"], "weak")
        self.assertEqual(fake.properties["alang"], "en,ja")
        self.assertEqual(fake.properties["audio-device"], "wasapi/speakers")
        backend.set_audio_delay(-2.75)
        self.assertEqual(fake.properties["audio-delay"], -2.75)
        self.assertEqual(backend.set_audio_device("missing/device"), "auto")
        backend.poll_timer.stop()

    def test_gapless_successor_is_appended_and_adopted_without_early_eof(self) -> None:
        backend, fake = self._backend()
        first = str(ROOT / "first.flac")
        second = str(ROOT / "second.flac")
        backend.is_loaded = True
        backend.current_source = first
        backend.set_gapless_mode("weak")
        self.assertTrue(backend.queue_gapless(second))
        self.assertIn(("loadfile", second, "append"), fake.commands)
        advanced: list[str] = []; ended: list[bool] = []
        backend.gaplessAdvanced.connect(advanced.append)
        backend.fileEnded.connect(lambda: ended.append(True))
        fake.properties["path"] = second
        backend._poll_state()
        self.assertEqual(advanced, [second])
        self.assertEqual(ended, [])
        self.assertTrue(backend.consume_gapless_transition(second))
        fake.properties["eof-reached"] = True
        backend._poll_state()
        self.assertEqual(ended, [True])
        backend.poll_timer.stop()

    def test_language_and_smtc_button_normalization(self) -> None:
        self.assertEqual(normalize_language_code("ENG-US"), "en")
        self.assertEqual(normalize_language_code("jpn"), "ja")
        self.assertEqual(normalize_language_preferences("EN, eng; JPN und"), "en,ja")
        controller = WindowsMediaController(enabled=False)
        actions: list[str] = []
        controller.actionRequested.connect(actions.append)
        controller._button_pressed(None, SimpleNamespace(button=SimpleNamespace(name="NEXT")))
        self.assertEqual(actions, ["next"])
        controller.shutdown()

    def test_dsd_stream_detection_and_raw_media_key_fallback(self) -> None:
        backend, fake = self._backend()
        backend.current_source = str(ROOT / "recording.dsf")
        fake.track_list = [{"type": "audio", "selected": True, "codec": "dsd_lsbf_planar", "lang": "ENG"}]
        info: list[dict[str, object]] = []
        backend.mediaInfoChanged.connect(info.append)
        backend._emit_media_info()
        self.assertTrue(info[-1]["is_dsd"])
        self.assertEqual(info[-1]["audio_language"], "en")
        backend.poll_timer.stop()

        class Player:
            def __init__(self) -> None:
                self.calls: list[object] = []

            def set_paused(self, value: bool) -> None: self.calls.append(("paused", value))
            def play_pause(self) -> None: self.calls.append("toggle")
            def stop(self) -> None: self.calls.append("stop")

        class Window(QObject):
            def __init__(self) -> None:
                super().__init__(); self.player = Player(); self.calls: list[str] = []

            def _play_next(self) -> None: self.calls.append("next")
            def _play_previous(self) -> None: self.calls.append("previous")

        window = Window(); inputs = PlayerInputController(window)
        inputs.handle_key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaNext, Qt.KeyboardModifier.NoModifier))
        inputs.handle_key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaPause, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(window.calls, ["next"])
        self.assertEqual(window.player.calls, [("paused", True)])


if __name__ == "__main__":
    unittest.main()
