"""Section 2 window, OSC, geometry, and buffering contract tests."""

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

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

from config.settings import SettingsStore
from core.player_backend import PlayerBackend
from core.preferences import (
    DONT_HIDE_CURSOR_FULLSCREEN_WHILE_OSC_VISIBLE,
    ENABLE_TITLE_BAR_AND_OSC,
    HIDE_OSC_WHEN_CURSOR_OUTSIDE,
)
from ui.geometry import RECT, WMSZ_RIGHT, correct_sizing_rect, point_from_lparam
from ui.osc_layout_constants import (
    FULLSCREEN_TOP_OSC_HEIGHT,
    MIN_WINDOW_SIZE,
    QUICK_SETTINGS_PANEL_WIDTH,
    SETTINGS_PANEL_WIDTH,
    SIDEBAR_MINIMUM_WIDTH,
    TITLE_AND_TOP_OSC_HEIGHT,
    TITLE_BAR_HEIGHT,
    TOP_OSC_MARGIN_FULLSCREEN,
    TOP_OSC_MARGIN_NORMAL,
)
from ui.window_mode import FullscreenState, WindowMode, WindowModeController


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class _Control:
    def set_fullscreen(self, _enabled: bool) -> None:
        pass

    def set_playlist_visible(self, _visible: bool) -> None:
        pass


class _Title:
    def set_maximized(self, _enabled: bool) -> None:
        pass


class _FullscreenWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(800, 450)
        self.control_bar = _Control()
        self.title_bar = _Title()
        self.playlist_panel = QWidget(self)
        self._chrome_visible = True
        self.change = None
        self.complete = None

    def _prepare_mode_transition(self) -> None:
        pass

    def _position_overlays(self) -> None:
        pass

    def _apply_mode_layout(self) -> None:
        pass

    def _animate_fullscreen_change(self, change: object, complete: object) -> None:
        self.change = change
        self.complete = complete


class Section2WindowOscTests(unittest.TestCase):
    def test_verified_layout_constants_and_exact_preferences(self) -> None:
        self.assertEqual(TITLE_BAR_HEIGHT, 28)
        self.assertEqual(TITLE_AND_TOP_OSC_HEIGHT, 62)
        self.assertEqual(FULLSCREEN_TOP_OSC_HEIGHT, 34)
        self.assertEqual((TOP_OSC_MARGIN_NORMAL, TOP_OSC_MARGIN_FULLSCREEN), (26, 6))
        self.assertEqual(SIDEBAR_MINIMUM_WIDTH, 240)
        self.assertEqual(QUICK_SETTINGS_PANEL_WIDTH, 360)
        self.assertEqual(SETTINGS_PANEL_WIDTH, 360)
        self.assertLessEqual(MIN_WINDOW_SIZE[0], 330)
        with TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            settings.load()
            self.assertTrue(settings.get(ENABLE_TITLE_BAR_AND_OSC))
            self.assertTrue(settings.get(HIDE_OSC_WHEN_CURSOR_OUTSIDE))
            self.assertFalse(settings.get(DONT_HIDE_CURSOR_FULLSCREEN_WHILE_OSC_VISIBLE))
            self.assertFalse(settings.get("ui.disableWindowAnimation"))

    def test_live_sizing_uses_video_region_after_sidebar_and_bottom_dock(self) -> None:
        rect = RECT(0, 0, 1000, 600)
        correct_sizing_rect(rect, WMSZ_RIGHT, 16 / 9, 360, 34, 285, 130)
        self.assertEqual(rect.right - rect.left, 1000)
        self.assertEqual(rect.bottom - rect.top, 394)

    def test_hit_test_coordinates_support_negative_monitor_origins(self) -> None:
        packed = ((-20 & 0xFFFF) << 16) | (-120 & 0xFFFF)
        self.assertEqual(point_from_lparam(packed), (-120, -20))

    def test_fullscreen_state_machine_rejects_racing_toggle_and_esc_queues_exit(self) -> None:
        window = _FullscreenWindow()
        window.show()
        controller = WindowModeController(window)
        controller.toggle_fullscreen()
        self.assertEqual(controller.fullscreen_state, FullscreenState.ANIMATING_TO_FULLSCREEN)
        controller.toggle_fullscreen()
        self.assertEqual(controller.fullscreen_state, FullscreenState.ANIMATING_TO_FULLSCREEN)
        controller.exit_fullscreen()
        self.assertTrue(controller._pending_fullscreen_exit)
        window.change()
        window.complete()
        self.assertEqual(controller.fullscreen_state, FullscreenState.ANIMATING_TO_WINDOWED)
        window.change()
        window.complete()
        self.assertEqual(controller.fullscreen_state, FullscreenState.WINDOWED)
        self.assertEqual(controller.mode, WindowMode.NORMAL)
        window.close()

    def test_buffering_percentage_is_forwarded_only_from_real_cache_stall(self) -> None:
        class FakeMpv:
            time_pos = 1.0
            duration = 20.0
            pause = False
            paused_for_cache = True
            cache_buffering_state = 43.4
            track_list: list[dict] = []

            def _get_property(self, name: str) -> object:
                return {
                    "paused-for-cache": True,
                    "cache-buffering-state": 43.4,
                    "seeking": False,
                    "demuxer-cache-state": {},
                    "eof-reached": False,
                    "path": "",
                    "vf": [],
                    "af": [],
                }.get(name)

        fake = FakeMpv()
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", fake)):
            backend = PlayerBackend()
        backend.is_loaded = True
        states: list[tuple[bool, int]] = []
        backend.bufferingStateChanged.connect(lambda active, percent: states.append((active, percent)))
        backend._poll_state()
        self.assertEqual(states[-1], (True, 43))
        backend.poll_timer.stop()

    def test_cached_mpv_state_does_not_suppress_timeline_ui_signals(self) -> None:
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
            backend = PlayerBackend()
        positions: list[float] = []
        durations: list[float] = []
        pauses: list[bool] = []
        backend.timeChanged.connect(positions.append)
        backend.durationChanged.connect(durations.append)
        backend.pauseStateChanged.connect(pauses.append)

        # Model PlayerState's queued slot running before PlayerBackend's slot.
        backend._position = 12.5
        backend._duration = 90.0
        backend._paused = False
        backend._on_position_changed(12.5)
        backend._on_duration_changed(90.0)
        backend._on_pause_changed(False)

        self.assertEqual(positions, [12.5])
        self.assertEqual(durations, [90.0])
        self.assertEqual(pauses, [False])
        backend.poll_timer.stop()

    def test_native_architecture_is_present_without_replacing_render_surface(self) -> None:
        main = (PACKAGE / "ui/main_window.py").read_text(encoding="utf-8")
        video = (PACKAGE / "ui/video_widget.py").read_text(encoding="utf-8")
        engine = (PACKAGE / "core/mpv_engine.py").read_text(encoding="utf-8")
        manager = (PACKAGE / "ui/player_window_manager.py").read_text(encoding="utf-8")
        self.assertIn("WM_NCCALCSIZE", main)
        self.assertIn("WM_NCHITTEST", main)
        self.assertIn("HTMAXBUTTON", main)
        self.assertIn("WM_SIZING", main)
        self.assertIn("startSystemMove", main)
        self.assertNotIn("AltModifier", main[main.index("def _perform_resize"):])
        self.assertIn("createWindowContainer", video)
        self.assertIn('keepaspect_window="no"', engine)
        self.assertIn("rendererReady.connect", manager)
        self.assertLess(manager.index("_show_startup_window()"), manager.index("renderer_active"))


if __name__ == "__main__":
    unittest.main()
