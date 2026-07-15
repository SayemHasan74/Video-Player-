"""Acceptance coverage for independent PiP and window geometry behavior."""

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

from PyQt6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from ui.main_window import MainWindow
from ui.window_mode import WindowMode


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class PipGeometryFullscreenTests(unittest.TestCase):
    def _window(self, root: Path, values: dict[str, object] | None = None) -> MainWindow:
        settings = SettingsStore(root / "settings.json"); settings.load()
        settings.set("startup.show_welcome", False)
        settings.set("ui.animations", False)
        for key, value in (values or {}).items(): settings.set(key, value)
        history = HistoryManager(root / "history.sqlite3")
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
            window = MainWindow(settings, history, [])
        window.show(); APP.processEvents()
        return window

    @staticmethod
    def _dispose(window: MainWindow) -> None:
        if window.window_modes.is_pip:
            window.window_modes.exit_pip()
        window.close(); window.deleteLater(); APP.processEvents()

    def test_minimize_to_pip_is_video_only_and_excludes_music_mode(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"window.minimize_to_pip_video": True})
            window.player.is_loaded = True
            window._last_media_info = {"has_video": False, "has_audio": True}
            with patch.object(window.window_modes, "enter_pip") as enter:
                window.showMinimized(); APP.processEvents(); window._enter_pip_after_minimize()
                enter.assert_not_called()
                window.showNormal(); APP.processEvents()
                window._last_media_info = {"has_video": True, "has_audio": True}
                window.showMinimized(); APP.processEvents(); window._enter_pip_after_minimize()
                enter.assert_called_once()
                enter.reset_mock(); window.showNormal(); APP.processEvents()
                window.window_modes.mode = WindowMode.COMPACT
                window.showMinimized(); APP.processEvents(); window._enter_pip_after_minimize()
                enter.assert_not_called()
                window.window_modes.mode = WindowMode.NORMAL
            self._dispose(window)

    def test_video_dimensions_drive_auto_resize_and_aspect_locked_manual_resize(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"playback.auto_resize": True})
            info = {"source": "movie.mkv", "has_video": True, "video_width": 1920, "video_height": 1080, "video_aspect": 16 / 9}
            window._media_info_changed(info); APP.processEvents()
            self.assertAlmostEqual(window.width() / window.height(), 16 / 9, delta=0.03)
            window.setGeometry(100, 100, 900, 506); APP.processEvents()
            window._resize_edge = "right"
            window._resize_geometry = window.geometry()
            window._resize_start = QPoint(1000, 350)
            with patch.object(QApplication, "keyboardModifiers", return_value=Qt.KeyboardModifier.NoModifier):
                window._perform_resize(QPoint(1160, 350)); window._apply_pending_resize()
            self.assertAlmostEqual(window.width() / window.height(), 16 / 9, delta=0.03)
            locked_height = window.height()
            window._resize_geometry = window.geometry(); window._resize_start = QPoint(1160, 350)
            with patch.object(QApplication, "keyboardModifiers", return_value=Qt.KeyboardModifier.AltModifier):
                window._perform_resize(QPoint(1260, 350)); window._apply_pending_resize()
            self.assertEqual(window.height(), locked_height)
            self._dispose(window)

    def test_display_identity_is_persisted_and_fullscreen_keeps_osc_visible(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            window.move(42, 57); APP.processEvents(); window._save_geometry()
            self.assertTrue(window.settings.get("window.screen_name"))
            self.assertIsNotNone(window.settings.get("window.screen_offset_x"))
            window._toggle_fullscreen(); APP.processEvents()
            self.assertTrue(window.isFullScreen())
            self.assertTrue(window.title_bar.isVisible())
            self.assertTrue(window.control_bar.isVisible())
            window._toggle_fullscreen(); APP.processEvents()
            self.assertFalse(window.isFullScreen())
            self._dispose(window)

    def test_fullscreen_transition_fades_and_finishes_at_full_opacity(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"ui.animations": True})
            with patch("ui.main_window.transitions_enabled", return_value=True):
                window._toggle_fullscreen()
                self.assertTrue(window.window_modes.transitioning)
                loop = QEventLoop(); QTimer.singleShot(800, loop.quit); loop.exec()
            self.assertTrue(window.isFullScreen())
            self.assertFalse(window.window_modes.transitioning)
            self.assertAlmostEqual(window.windowOpacity(), 1.0)
            window.settings.set("ui.animations", False)
            window._toggle_fullscreen(); APP.processEvents()
            self._dispose(window)

    def test_optional_video_drag_moves_window_and_video_scroll_setting_is_independent(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory), {"window.drag_from_video": True, "ui.video_scroll_enabled": False, "ui.osc_scroll_enabled": True})
            start = window.frameGeometry().topLeft()
            window._start_video_window_drag(QPoint(300, 300))
            window._move_video_window_drag(QPoint(340, 325))
            self.assertEqual(window.frameGeometry().topLeft(), start + QPoint(40, 25))
            with patch.object(window.player, "change_volume") as volume:
                window._handle_video_scroll(5)
                volume.assert_not_called()
            self.assertTrue(window.settings.get("ui.osc_scroll_enabled"))
            window._end_video_window_drag()
            self._dispose(window)

    def test_pip_video_click_does_not_restore_the_main_window(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            window.window_modes.mode = WindowMode.PIP
            with patch.object(window, "_toggle_pip") as toggle:
                window._video_clicked()
                toggle.assert_not_called()
            window.window_modes.mode = WindowMode.NORMAL
            self._dispose(window)


if __name__ == "__main__":
    unittest.main()
