"""Acceptance coverage for the three complete shared-fragment OSC layouts."""

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

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from config.settings import SettingsStore
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from ui.control_bar import ControlBar
from ui.main_window import MainWindow
from ui.osc_toolbar_editor import OscToolbarEditor


APP = QApplication.instance() or QApplication([])


def wheel(delta: int = 120) -> QWheelEvent:
    return QWheelEvent(
        QPointF(80, 8), QPointF(80, 8), QPoint(), QPoint(0, delta),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )


class OscLayoutTests(unittest.TestCase):
    @staticmethod
    def _dispose(widget: object) -> None:
        widget.close()
        widget.deleteLater()
        APP.processEvents()

    def _window(self, root: Path) -> MainWindow:
        settings = SettingsStore(root / "settings.json")
        settings.load()
        settings.set("startup.show_welcome", False)
        history = HistoryManager(root / "history.sqlite3")
        with patch.object(PlayerBackend, "_load_mpv", lambda backend: setattr(backend, "mpv", None)):
            window = MainWindow(settings, history, [])
        window.resize(1100, 680)
        window.show()
        APP.processEvents()
        return window

    def test_all_layouts_reuse_the_exact_same_control_fragments_and_buttons(self) -> None:
        bar = ControlBar()
        bar.resize(1100, 82)
        identities = tuple(map(id, (bar.timeline, bar.transport, bar.audio_controls, bar.toolbar)))
        signals = {
            "previous": (bar.previousClicked, bar.previous_button),
            "play": (bar.playPauseClicked, bar.play_button),
            "next": (bar.nextClicked, bar.next_button),
            "stop": (bar.stopClicked, bar.stop_button),
            "playlist": (bar.playlistClicked, bar.playlist_button),
            "subtitle": (bar.subtitleClicked, bar.subtitle_button),
            "audio": (bar.audioClicked, bar.audio_button),
            "screenshot": (bar.screenshotClicked, bar.screenshot_button),
            "ab": (bar.abLoopClicked, bar.ab_button),
            "pip": (bar.pipClicked, bar.pip_button),
            "music": (bar.musicClicked, bar.music_button),
            "cover": (bar.coverClicked, bar.cover_button),
            "fullscreen": (bar.fullscreenClicked, bar.fullscreen_button),
        }
        spies = {name: QSignalSpy(signal) for name, (signal, _button) in signals.items()}
        for pass_index, mode in enumerate(("floating", "top", "bottom"), 1):
            bar.set_layout_mode(mode)
            bar.resize(1100, bar.height())
            APP.processEvents()
            self.assertEqual(tuple(map(id, (bar.timeline, bar.transport, bar.audio_controls, bar.toolbar))), identities)
            for name, (_signal, button) in signals.items():
                button.click()
                self.assertEqual(len(spies[name]), pass_index, f"{name} failed in {mode}")
        self._dispose(bar)

    def test_seek_and_volume_scroll_work_and_can_be_disabled_in_every_layout(self) -> None:
        bar = ControlBar()
        seek_spy = QSignalSpy(bar.seekRequested)
        volume_spy = QSignalSpy(bar.volumeWheel)
        bar.set_time(50, 100)
        for mode in ("floating", "top", "bottom"):
            bar.set_layout_mode(mode)
            bar.seekbar.setValue(500)
            bar.seekbar.wheelEvent(wheel())
            bar.volume.wheelEvent(wheel())
        self.assertEqual(len(seek_spy), 3)
        self.assertEqual(len(volume_spy), 3)
        self.assertTrue(all(abs(float(entry[0]) - 55.0) < 0.01 for entry in seek_spy))
        bar.set_scroll_enabled(False)
        bar.seekbar.wheelEvent(wheel())
        bar.volume.wheelEvent(wheel())
        self.assertEqual((len(seek_spy), len(volume_spy)), (3, 3))
        self._dispose(bar)

    def test_timeline_tracks_buffers_chapters_and_elapsed_remaining_toggle(self) -> None:
        bar = ControlBar()
        bar.set_time(20, 100)
        bar.set_buffered_ranges([(0, 35), (50, 70)])
        bar.set_chapters([{"time": 10}, {"start_time": 60}])
        self.assertEqual(bar.elapsed_label.text(), "00:20")
        self.assertEqual(bar.remaining_label.text(), "01:40")
        bar.remaining_label.clicked.emit()
        self.assertEqual(bar.remaining_label.text(), "−01:20")
        self.assertEqual(bar.seekbar._buffered_ranges, [(0.0, 35.0), (50.0, 70.0)])
        self.assertEqual(bar.seekbar._chapter_times, [10.0, 60.0])
        self._dispose(bar)

    def test_layout_geometry_is_distinct_and_bottom_dock_never_wobbles_video(self) -> None:
        with TemporaryDirectory() as directory:
            window = self._window(Path(directory))
            shell = window.central_shell.rect()
            window.settings.set("ui.osc_position", "floating")
            window._apply_ui_preferences()
            floating = window.control_bar.geometry()
            self.assertGreater(floating.x(), 0)
            self.assertLess(floating.width(), shell.width())
            self.assertEqual(window.video.geometry(), shell)
            old_y = floating.y()
            window.overlays.move_floating(-25)
            self.assertLess(window.control_bar.y(), old_y)

            window.settings.set("ui.osc_position", "top")
            window._apply_ui_preferences()
            self.assertEqual(window.control_bar.y(), 72)
            self.assertEqual(window.video.geometry(), shell)

            window.settings.set("ui.osc_position", "bottom")
            window._chrome_visible = True
            window._apply_ui_preferences()
            visible_video = window.video.geometry()
            self.assertEqual(visible_video.height(), shell.height() - window.control_bar.height())
            window._chrome_visible = False
            window.overlays.position()
            self.assertEqual(window.video.geometry(), visible_video)
            self._dispose(window)

    def test_toolbar_editor_and_fragment_preserve_user_order(self) -> None:
        editor = OscToolbarEditor(["fullscreen", "playlist", "music"])
        self.assertEqual(editor.selected_order(), ["fullscreen", "playlist", "music"])
        moved = editor.active.takeItem(2)
        editor.active.insertItem(0, moved)
        order = editor.selected_order()
        self.assertEqual(order, ["music", "fullscreen", "playlist"])
        bar = ControlBar()
        self.assertEqual(bar.set_toolbar_order(order), order)
        self.assertEqual(bar.toolbar.order, order)
        self._dispose(editor)
        self._dispose(bar)


if __name__ == "__main__":
    unittest.main()
