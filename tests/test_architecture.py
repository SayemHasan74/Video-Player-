"""Regression checks for the unified render and window architecture."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    def test_player_uses_libmpv_render_context_not_native_wid(self) -> None:
        backend = (ROOT / "prism_player/core/player_backend.py").read_text(encoding="utf-8")
        surface = (ROOT / "prism_player/ui/video_widget.py").read_text(encoding="utf-8")
        self.assertIn('"vo": "libmpv"', backend)
        self.assertIn("MpvRenderContext", surface)
        self.assertIn("QOpenGLWidget", surface)
        self.assertNotIn("winId(", backend + surface)
        self.assertNotIn('"wid"', backend)

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


if __name__ == "__main__":
    unittest.main()
