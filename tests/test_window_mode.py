"""State-machine regression tests independent of a visible desktop."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication, QWidget


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prism_player"))

from ui.window_mode import WindowMode, WindowModeController
from ui.pip_window import PipWindow


class _ControlBar:
    def __init__(self) -> None:
        self.fullscreen = False
        self.playlist_visible = False

    def set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen = enabled

    def set_playlist_visible(self, visible: bool) -> None:
        self.playlist_visible = visible


class _TitleBar:
    def __init__(self) -> None:
        self.maximized = False

    def set_maximized(self, maximized: bool) -> None:
        self.maximized = maximized


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def set(self, key: str, value: object) -> None:
        self.values[key] = value


class _RenderVideo(QWidget):
    """Tracks accidental renderer teardown during a top-level migration."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.shutdown_calls = 0

    def shutdown_renderer(self, permanent: bool = True) -> None:
        self.shutdown_calls += 1


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(900, 560)
        self.move(80, 90)
        self.control_bar = _ControlBar()
        self.title_bar = _TitleBar()
        self.central_shell = QWidget(self)
        self.central_shell.setGeometry(self.rect())
        self.video = _RenderVideo(self.central_shell)
        self.video.setGeometry(self.central_shell.rect())
        self.playlist_panel = QWidget(self)
        self.playlist_panel.show()
        self.settings = _Settings()
        self.player_session = object()
        self.hdr_state = {"primaries": "bt.2020", "transfer": "pq"}
        self.pip_window = PipWindow(self.settings)
        self._chrome_visible = True
        self.prepared = 0
        self.layouts = 0

    def _prepare_mode_transition(self) -> None:
        self.prepared += 1

    def _apply_mode_layout(self) -> None:
        self.layouts += 1

    def _position_overlays(self) -> None:
        pass


class WindowModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = _Window()
        self.window.show()
        self.app.processEvents()
        self.original = QRect(self.window.geometry())
        self.controller = WindowModeController(self.window)

    def tearDown(self) -> None:
        self.window.pip_window.shutdown(self.window)
        self.window.close()

    def test_repeated_compact_toggle_restores_exact_state(self) -> None:
        for _ in range(5):
            self.controller.toggle_compact()
            self.assertEqual(self.controller.mode, WindowMode.COMPACT)
            self.assertEqual(self.window.height(), 140)
            self.assertFalse(self.window.playlist_panel.isVisible())
            self.controller.toggle_compact()
            self.assertEqual(self.controller.mode, WindowMode.NORMAL)
            self.assertEqual(self.window.geometry(), self.original)
            self.assertTrue(self.window.playlist_panel.isVisible())
        self.assertFalse(self.controller.transitioning)

    def test_fullscreen_round_trip_restores_geometry_and_playlist(self) -> None:
        self.controller.toggle_fullscreen()
        self.app.processEvents()
        self.assertEqual(self.controller.mode, WindowMode.FULLSCREEN)
        self.assertTrue(self.window.isFullScreen())
        self.assertFalse(self.window.playlist_panel.isVisible())
        self.controller.toggle_fullscreen()
        self.app.processEvents()
        self.assertEqual(self.controller.mode, WindowMode.NORMAL)
        self.assertEqual(self.window.geometry(), self.original)
        self.assertTrue(self.window.playlist_panel.isVisible())

    def test_pip_round_trip_restores_geometry_and_playlist(self) -> None:
        video = self.window.video
        session = self.window.player_session
        hdr_state = dict(self.window.hdr_state)
        self.controller.toggle_pip()
        self.app.processEvents()
        self.assertEqual(self.controller.mode, WindowMode.PIP)
        self.assertTrue(self.window.pip_window.isVisible())
        self.assertIs(video.parentWidget(), self.window.pip_window.video_host)
        self.assertFalse(self.window.isVisible())
        self.assertLessEqual(self.window.pip_window.grip.width(), 24)
        self.assertLessEqual(self.window.pip_window.grip.height(), 24)
        self.assertIs(self.window.player_session, session)
        self.assertEqual(self.window.hdr_state, hdr_state)
        self.controller.toggle_pip()
        self.app.processEvents()
        self.assertEqual(self.controller.mode, WindowMode.NORMAL)
        self.assertIs(video.parentWidget(), self.window.central_shell)
        self.assertFalse(self.window.pip_window.isVisible())
        self.assertEqual(self.window.geometry(), self.original)
        self.assertTrue(self.window.playlist_panel.isVisible())
        self.assertIs(self.window.player_session, session)
        self.assertEqual(self.window.hdr_state, hdr_state)
        self.assertEqual(video.shutdown_calls, 0)

    def test_fullscreen_request_from_pip_restores_surface_before_switching_mode(self) -> None:
        video = self.window.video
        self.controller.toggle_pip()
        self.assertTrue(self.controller.is_pip)
        self.controller.toggle_fullscreen()
        self.app.processEvents()
        self.assertFalse(self.window.pip_window.isVisible())
        self.assertIs(video.parentWidget(), self.window.central_shell)
        self.assertEqual(self.controller.mode, WindowMode.FULLSCREEN)
        self.assertTrue(self.window.isFullScreen())
        self.controller.toggle_fullscreen()
        self.app.processEvents()
        self.assertEqual(self.controller.mode, WindowMode.NORMAL)
        self.assertEqual(self.window.geometry(), self.original)
        self.assertTrue(self.window.playlist_panel.isVisible())

    def test_compact_from_maximized_preserves_normal_geometry(self) -> None:
        self.window.showMaximized()
        self.app.processEvents()
        self.controller.sync_from_window()
        self.controller.toggle_compact()
        self.controller.toggle_compact()
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.window.showNormal()
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), self.original)


if __name__ == "__main__":
    unittest.main()
