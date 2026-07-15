"""Acceptance coverage for the shared advanced sidebar coordinator."""

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

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class AdvancedSidebarTests(unittest.TestCase):
    @staticmethod
    def _dispose(window: MainWindow) -> None:
        window.close()
        window.deleteLater()
        APP.processEvents()

    def _window(self, root: Path, values: dict[str, object] | None = None) -> MainWindow:
        settings = SettingsStore(root / "settings.json")
        settings.load()
        settings.set("startup.show_welcome", False)
        for key, value in (values or {}).items():
            settings.set(key, value)
        history = HistoryManager(root / "history.sqlite3")
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
            window = MainWindow(settings, history, [])
        window.resize(1100, 680)
        window.show()
        APP.processEvents()
        window._position_overlays()
        return window

    def test_playlist_and_exact_same_quick_settings_widget_pin_opposite(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": False})
            quick = window.playlist_panel.quick_settings
            window.sidebars.set_playlist_pinned(True)
            window.sidebars.set_quick_pinned(True)
            APP.processEvents()
            tab_ids = [window.playlist_panel.tabs.tabBar().tabData(i) for i in range(window.playlist_panel.tabs.count())]
            self.assertNotIn("quick_settings", tab_ids)
            self.assertIs(window.playlist_panel.quick_settings, quick)
            self.assertIs(quick.parentWidget(), window.sidebars.quick_dock)
            self.assertTrue(window.playlist_panel.isVisible())
            self.assertTrue(window.sidebars.quick_dock.isVisible())
            self.assertEqual(window.playlist_panel._side, "right")
            self.assertEqual(window.sidebars.quick_dock._side, "left")
            self.assertLess(window.video.width(), window.central_shell.width())
            window.sidebars.set_quick_pinned(False)
            APP.processEvents()
            self.assertIs(window.playlist_panel.quick_settings, quick)
            self.assertGreaterEqual(window.playlist_panel.tabs.indexOf(quick), 0)
            tab_ids = [window.playlist_panel.tabs.tabBar().tabData(i) for i in range(window.playlist_panel.tabs.count())]
            self.assertEqual(tab_ids[:3], ["playlist", "chapters", "quick_settings"])
            self._dispose(window)

    def test_unpinned_slide_overlays_video_without_resizing_it(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": True})
            widths: list[int] = []
            heights: list[int] = []
            with patch("ui.sidebar_controller.transitions_enabled", return_value=True):
                window.sidebars.set_playlist_visible(True)
            animation = window.sidebars._animations["playlist"]
            animation.valueChanged.connect(
                lambda _value: (widths.append(window.video.width()), heights.append(window.video.height()))
            )
            loop = QEventLoop()
            QTimer.singleShot(350, loop.quit)
            loop.exec()
            self.assertGreater(len(widths), 3)
            self.assertEqual(len(set(heights)), 1)
            self.assertEqual(len(set(widths)), 1)
            self.assertEqual(window.sidebars.playlist_progress, 1.0)
            self.assertLess(window.playlist_panel.x(), window.video.geometry().right())
            self._dispose(window)

    def test_reduced_motion_finishes_immediately_without_animation(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": True})
            with patch("ui.sidebar_controller.transitions_enabled", return_value=False):
                window.sidebars.set_playlist_visible(True)
            self.assertEqual(window.sidebars._animations, {})
            self.assertEqual(window.sidebars.playlist_progress, 1.0)
            self.assertTrue(window.playlist_panel.isVisible())
            self._dispose(window)

    def test_side_width_selected_tab_and_pins_restore(self) -> None:
        with TemporaryDirectory() as directory:
            values = {
                "ui.animations": False,
                "ui.sidebar_side": "left",
                "ui.sidebar_width": 390,
                "ui.quick_settings_width": 345,
                "ui.sidebar_tab": "quick_settings",
                "ui.playlist_pinned": True,
                "ui.quick_settings_pinned": True,
            }
            window = self._window(Path(directory), values)
            self.assertTrue(window.sidebars.playlist_pinned)
            self.assertTrue(window.sidebars.quick_pinned)
            self.assertEqual(window.playlist_panel.width(), 390)
            self.assertEqual(window.sidebars.quick_dock.width(), 345)
            self.assertEqual(window.playlist_panel._side, "left")
            self.assertEqual(window.sidebars.quick_dock._side, "right")
            self.assertEqual(window.settings.get("ui.sidebar_tab"), "quick_settings")
            window.sidebars.set_quick_pinned(False, animate=False)
            self.assertEqual(
                window.playlist_panel.tabs.tabBar().tabData(window.playlist_panel.tabs.currentIndex()),
                "quick_settings",
            )
            window.sidebars.set_playlist_width(420)
            window.sidebars.set_quick_width(365)
            self.assertEqual(window.settings.get("ui.sidebar_width"), 420)
            self.assertEqual(window.settings.get("ui.quick_settings_width"), 365)
            self._dispose(window)

    def test_unpinned_width_drag_resizes_only_the_playlist_overlay(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": False})
            window.sidebars.set_playlist_visible(True, animate=False)
            full_width = window.sidebars._base_rect.width()
            widths: list[int] = []
            original = window.video.setGeometry

            def record_geometry(*args) -> None:
                original(*args)
                widths.append(window.video.width())

            with patch.object(window.video, "setGeometry", side_effect=record_geometry):
                window.sidebars.set_playlist_width(420)
                loop = QEventLoop()
                QTimer.singleShot(30, loop.quit)
                loop.exec()
            self.assertEqual(widths, [])
            self.assertEqual(window.video.width(), full_width)
            self.assertEqual(window.playlist_panel.width(), 420)
            self._dispose(window)

    def test_pinned_playlist_reserves_video_space(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": False})
            full_width = window.sidebars._base_rect.width()
            window.sidebars.set_playlist_width(420)
            loop = QEventLoop(); QTimer.singleShot(30, loop.quit); loop.exec()
            window.sidebars.set_playlist_pinned(True)
            self.assertEqual(window.playlist_panel.width(), 420)
            self.assertEqual(window.video.width(), full_width - 420)
            window.sidebars.set_playlist_pinned(False)
            self.assertEqual(window.video.width(), full_width)
            self._dispose(window)

    def test_pinned_playlist_ignores_click_away_until_unpinned(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": False})
            window.sidebars.set_playlist_pinned(True)
            window.sidebars.request_close_playlist()
            self.assertTrue(window.sidebars.playlist_open)
            window.sidebars.set_playlist_pinned(False)
            window.sidebars.request_close_playlist()
            self.assertFalse(window.sidebars.playlist_open)
            self.assertFalse(window.playlist_panel.isVisible())
            self._dispose(window)


if __name__ == "__main__":
    unittest.main()
