"""Regression checks for the unified render and window architecture."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    def test_player_uses_libmpv_render_context_not_native_wid(self) -> None:
        backend = (ROOT / "prism_player/core/player_backend.py").read_text(encoding="utf-8")
        engine = (ROOT / "prism_player/core/mpv_engine.py").read_text(encoding="utf-8")
        surface = (ROOT / "prism_player/ui/video_widget.py").read_text(encoding="utf-8")
        render_window = (ROOT / "prism_player/ui/mpv_render_window.py").read_text(encoding="utf-8")
        self.assertIn('vo="libmpv"', engine)
        self.assertIn("MpvRenderContext", engine)
        self.assertIn("class MpvRenderWindow(QWindow)", render_window)
        self.assertIn("OpenGLSurface", render_window)
        self.assertIn("requestUpdate()", render_window)
        self.assertIn("createWindowContainer", surface)
        self.assertNotIn("QOpenGLWidget", engine + surface + render_window)
        self.assertNotIn("winId(", backend + engine + surface + render_window)
        self.assertNotIn('"wid"', backend + engine)

    def test_mpv_thread_bridge_state_and_single_owner_exist(self) -> None:
        signals = (ROOT / "prism_player/core/mpv_signals.py").read_text(encoding="utf-8")
        state = (ROOT / "prism_player/core/player_state.py").read_text(encoding="utf-8")
        engine = (ROOT / "prism_player/core/mpv_engine.py").read_text(encoding="utf-8")
        for name in (
            "position_changed", "duration_changed", "pause_changed", "file_loaded",
            "render_update", "property_changed", "mpv_shutdown", "log_message",
        ):
            self.assertIn(name, signals)
        self.assertIn("QueuedConnection", state)
        self.assertIn("observe_property", engine)
        self.assertNotIn("poll_timer.start", (ROOT / "prism_player/core/player_backend.py").read_text(encoding="utf-8"))
        direct_imports = []
        for path in (ROOT / "prism_player").rglob("*.py"):
            if "import mpv" in path.read_text(encoding="utf-8"):
                direct_imports.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(direct_imports, ["prism_player/core/mpv_engine.py"])

    def test_no_native_global_mouse_filter_or_geometry_retries(self) -> None:
        window = (ROOT / "prism_player/ui/main_window.py").read_text(encoding="utf-8")
        modes = (ROOT / "prism_player/ui/window_mode.py").read_text(encoding="utf-8")
        combined = window + modes
        self.assertNotIn("installNativeEventFilter", combined)
        self.assertNotIn("QAbstractNativeEventFilter", combined)
        self.assertNotIn("WM_MBUTTONDOWN", combined)
        self.assertNotIn("stabilize_compact_geometry", combined)
        self.assertNotIn("stabilize_restored_geometry", combined)
        self.assertNotIn("_mini_transition_serial", combined)

    def test_window_responsibilities_are_split_into_controllers(self) -> None:
        window = (ROOT / "prism_player/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("WindowModeController", window)
        self.assertIn("OverlayController", window)
        self.assertIn("PlayerInputController", window)
        self.assertIn("PlayerSession", window)
        self.assertIn("MediaOpenController", window)
        self.assertIn("MediaStateController", window)
        self.assertIn("PlaybackEventRouter", window)
        self.assertIn("PluginUiController", window)
        self.assertIn("MusicModeController", window)
        self.assertTrue((ROOT / "prism_player/ui/window_mode.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/overlay_controller.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/input_controller.py").exists())
        self.assertTrue((ROOT / "prism_player/core/player_session.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/media_open_controller.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/media_state_controller.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/playback_event_router.py").exists())
        self.assertTrue((ROOT / "prism_player/ui/plugin_ui_controller.py").exists())
        music = (ROOT / "prism_player/ui/music_mode.py").read_text(encoding="utf-8")
        self.assertNotIn("PlayerBackend(", music)
        self.assertNotIn("PlaylistPanel(", music)

    def test_playlist_is_an_in_tree_overlay(self) -> None:
        panel = (ROOT / "prism_player/ui/playlist_panel.py").read_text(encoding="utf-8")
        window = (ROOT / "prism_player/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("super().__init__(parent)", panel)
        self.assertNotIn("Qt.WindowType.Tool", panel)
        self.assertIn("self.playlist_panel.setParent(central)", window)

    def test_native_video_keeps_native_widget_overlays_above_it(self) -> None:
        stack = (ROOT / "prism_player/ui/native_overlay_stack.py").read_text(encoding="utf-8")
        window = (ROOT / "prism_player/ui/main_window.py").read_text(encoding="utf-8")
        overlays = (ROOT / "prism_player/ui/overlay_controller.py").read_text(encoding="utf-8")
        self.assertIn("WA_NativeWindow", stack)
        self.assertIn("SetWindowPos", stack)
        self.assertIn("SWP_NOACTIVATE", stack)
        self.assertIn("NativeOverlayStack", window)
        for name in (
            "self.title_bar", "self.control_bar", "self.playlist_panel", "self.osd",
            "self.buffering_indicator", "self.thumbnail_preview", "self.crop_overlay",
        ):
            self.assertIn(name, window)
        self.assertIn("native_overlays.raise_widget", overlays)


if __name__ == "__main__":
    unittest.main()
