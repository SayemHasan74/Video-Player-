"""Root application window and component controller."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QCursor, QDragEnterEvent, QDropEvent, QIcon, QKeyEvent, QShortcut
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QWidget

from config.settings import APP_NAME, CONTROL_BAR_HEIGHT, DEFAULT_WINDOW_SIZE, MIN_WINDOW_SIZE, PLAYLIST_PANEL_WIDTH, SettingsStore, TITLE_BAR_HEIGHT
from core.history_manager import HistoryManager
from core.player_backend import PlayerBackend
from core.playlist_manager import PlaylistItem, PlaylistManager
from core.url_resolver import UrlResolverWorker
from ui.control_bar import ControlBar
from ui.open_url_dialog import OpenUrlDialog
from ui.osd import OSDLabel
from ui.pip_window import PiPWindow
from ui.playlist_panel import PlaylistPanel
from ui.settings_dialog import SettingsDialog
from ui.subtitle_finder_dialog import SubtitleFinderDialog
from ui.title_bar import TitleBar
from ui.track_menu import TrackMenuFactory
from ui.video_widget import VideoWidget
from utils.file_utils import is_media_file, is_probable_url, scan_media_files
from utils.time_utils import format_time


class FolderScanWorker(QThread):
    """Scan folders for media files without blocking the UI."""

    scanned = pyqtSignal(list)

    def __init__(self, paths: list[Path], recursive: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.recursive = recursive

    def run(self) -> None:
        self.scanned.emit(scan_media_files(self.paths, self.recursive))


class MainWindow(QMainWindow):
    """Frameless Comet Player main window."""

    def __init__(self, settings: SettingsStore, history: HistoryManager, startup_files: list[Path] | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.history = history
        self.logger = logging.getLogger(__name__)
        self.playlist = PlaylistManager(self)
        self.video = VideoWidget(self)
        self.title_bar = TitleBar(self)
        self.control_bar = ControlBar(self)
        self.playlist_panel = PlaylistPanel(self.video)
        self.osd = OSDLabel(self.video)
        self.drop_overlay = QLabel("Drop to play", self.video)
        self.track_menus = TrackMenuFactory(self)
        self.pip_window: PiPWindow | None = None
        self.url_worker: UrlResolverWorker | None = None
        self.folder_worker: FolderScanWorker | None = None
        self.audio_tracks: list[dict] = []
        self.subtitle_tracks: list[dict] = []
        self._drag_start: QPoint | None = None
        self._window_start: QPoint | None = None
        self._resize_edge = ""
        self._resize_geometry = QRect()
        self._resize_start = QPoint()
        self._ab_a: float | None = None
        self._ab_b: float | None = None
        self._cover_mode = False
        self._chrome_visible = True
        self._is_playing = False
        self._chrome_animation: QParallelAnimationGroup | None = None
        self._mini_mode = False
        self._pre_mini_geometry = QRect()
        self._pre_mini_fullscreen = False
        self._pre_mini_maximized = False
        self.central_shell: QWidget | None = None
        self._hide_chrome_timer = QTimer(self)
        self._hide_chrome_timer.setSingleShot(True)
        self._hide_chrome_timer.timeout.connect(self._hide_player_chrome)
        self._current_duration = 0.0
        self._current_position = 0.0
        self._build_window()
        self.player = PlayerBackend(self.video, self)
        self._connect_signals()
        self._restore_geometry()
        self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)), announce=False)
        self._show_startup_window()
        if startup_files:
            self.open_files(startup_files, append=False)

    def open_files(self, files: list[Path], append: bool = False) -> None:
        """Add files to the playlist and start playback."""
        media = [path for path in files if is_media_file(path)]
        if not media:
            self.osd.show_message("No supported media files found", "warning")
            return
        self.playlist.add_sources(media, append=append)
        if not append or self.playlist.current_index == -1:
            self.playlist.set_current(0)
        elif self.player.is_loaded is False:
            self.playlist.set_current(self.playlist.current_index)

    def open_url(self, url: str) -> None:
        """Resolve and play an online URL."""
        self.osd.show_message("Resolving URL...")
        self.url_worker = UrlResolverWorker(url, str(self.settings.get("network.preferred_format", "bestvideo+bestaudio/best")), self)
        self.url_worker.resolved.connect(lambda resolved, title: self._play_resolved_url(url, resolved, title))
        self.url_worker.failed.connect(lambda error: self.osd.show_message(f"URL failed: {error}", "error"))
        self.url_worker.start()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._position_overlays()
        self.title_bar.set_maximized(self.isMaximized())

    def moveEvent(self, event: object) -> None:
        super().moveEvent(event)
        self._position_overlays()

    def changeEvent(self, event: object) -> None:
        super().changeEvent(event)
        if self.isMinimized():
            self.title_bar.hide()
            self.control_bar.hide()
        else:
            self.title_bar.show()
            self.control_bar.show()
            self._position_overlays()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        current = self.playlist.current_item()
        if current is not None and self.settings.get("playback.remember_position", True):
            self.history.save_position(current.source, current.title, self._current_position, self._current_duration)
        self.settings.set("playback.volume", self.control_bar.volume.slider.value())
        self.settings.save()
        if self.pip_window is not None:
            self.pip_window.close()
        self.title_bar.close()
        self.control_bar.close()
        self.player.shutdown()
        self.history.close()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or (mime.hasText() and is_probable_url(mime.text())):
            event.acceptProposedAction()
            self.drop_overlay.show()
            self.drop_overlay.raise_()

    def dragLeaveEvent(self, event: object) -> None:
        self.drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_overlay.hide()
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        urls = [url.toString() for url in event.mimeData().urls() if not url.isLocalFile()]
        if not urls and event.mimeData().hasText() and is_probable_url(event.mimeData().text()):
            urls.append(event.mimeData().text().strip())
        append = bool(event.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        recursive = bool(event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        folders = [path for path in paths if path.is_dir()]
        files = [path for path in paths if path.is_file()]
        if folders:
            self.folder_worker = FolderScanWorker(folders, recursive, self)
            self.folder_worker.scanned.connect(lambda found: self.open_files(found, append=append))
            self.folder_worker.start()
        if files:
            self.open_files(files, append=append)
        if urls:
            self._show_url_dialog(urls[0])
        event.acceptProposedAction()

    def mouseMoveEvent(self, event: object) -> None:
        if self._resize_edge:
            self._perform_resize(event.globalPosition().toPoint())
            return
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_at(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_geometry = self.geometry()
                self._resize_start = event.globalPosition().toPoint()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        self._resize_edge = ""
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle shortcuts even when focus is on a control overlay."""
        if event.isAutoRepeat():
            event.ignore()
            return
        self._handle_key(event)

    def _build_window(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / "assets" / "prism_logo.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.resize(*DEFAULT_WINDOW_SIZE)
        central = QWidget(self)
        self.central_shell = central
        central.setStyleSheet("background: #0d0d0d;")
        self.setCentralWidget(central)
        self.video.setParent(central)
        self.title_bar.setParent(central)
        self.control_bar.setParent(central)
        for chrome in (self.title_bar, self.control_bar):
            chrome.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            chrome.raise_()
        self.drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_overlay.setStyleSheet(
            "QLabel { color: #f2f2f2; border: 2px solid #eeeeee; "
            "background: rgba(255,255,255,28); font-size: 18px; font-weight: 600; }"
        )
        self.drop_overlay.hide()
        self.playlist_panel.hide()
        self._position_overlays()

    def _connect_signals(self) -> None:
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        self.title_bar.maximizeClicked.connect(self._toggle_maximized)
        self.title_bar.closeClicked.connect(self.close)
        self.title_bar.dragStarted.connect(self._start_window_drag)
        self.title_bar.dragMoved.connect(self._move_window_drag)
        self.video.doubleClicked.connect(self.player.play_pause)
        self.video.rightClicked.connect(self._show_context_menu)
        self.video.scrolled.connect(self._handle_video_scroll)
        self.video.mouseMoved.connect(self._show_controls)
        self.video.mousePositionChanged.connect(self._handle_video_mouse_position)
        self.video.keyPressed.connect(self._handle_key)
        self.control_bar.playPauseClicked.connect(self.player.play_pause)
        self.control_bar.stopClicked.connect(self.player.stop)
        self.control_bar.nextClicked.connect(self._play_next)
        self.control_bar.previousClicked.connect(self._play_previous)
        self.control_bar.seekRequested.connect(self.player.seek_absolute)
        self.control_bar.volumeChanged.connect(self.player.set_volume)
        self.control_bar.muteClicked.connect(self.player.toggle_mute)
        self.control_bar.volumeWheel.connect(self.player.change_volume)
        self.control_bar.speedChanged.connect(self.player.set_speed)
        self.control_bar.abLoopClicked.connect(self._cycle_ab_loop)
        self.control_bar.screenshotClicked.connect(self._save_screenshot)
        self.control_bar.subtitleClicked.connect(self._show_subtitle_menu)
        self.control_bar.audioClicked.connect(self._show_audio_menu)
        self.control_bar.playlistClicked.connect(self._toggle_playlist)
        self.control_bar.pipClicked.connect(self._toggle_pip)
        self.control_bar.coverClicked.connect(self._toggle_cover_mode)
        self.control_bar.fullscreenClicked.connect(self._toggle_fullscreen)
        self.playlist.currentItemChanged.connect(self._load_playlist_item)
        self.playlist.playlistChanged.connect(self._refresh_playlist)
        self.playlist_panel.itemActivated.connect(self.playlist.set_current)
        self.playlist_panel.removeRequested.connect(self.playlist.remove)
        self.player.timeChanged.connect(self._time_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.pauseStateChanged.connect(self.control_bar.set_paused)
        self.player.pauseStateChanged.connect(self._playback_state_changed)
        self.player.volumeChanged.connect(self.control_bar.set_volume_state)
        self.player.speedChanged.connect(self.control_bar.set_speed)
        self.player.tracksChanged.connect(self._tracks_changed)
        self.player.fileEnded.connect(self._play_next)
        self.player.error.connect(lambda text: self.osd.show_message(text, "error"))
        self.control_bar.set_cover_mode(self._cover_mode)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.video.installEventFilter(self)
        self.title_bar.installEventFilter(self)
        self.control_bar.installEventFilter(self)
        QShortcut(Qt.Key.Key_Return, self, activated=lambda: None if self.isFullScreen() else self._toggle_fullscreen())
        QShortcut(Qt.Key.Key_Enter, self, activated=lambda: None if self.isFullScreen() else self._toggle_fullscreen())
        QShortcut(Qt.Key.Key_Escape, self, activated=self._pause_and_minimize)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if self._handle_window_edge_event(watched, event):
            return True
        if watched is self.title_bar or watched is self.control_bar:
            if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._show_player_chrome()
                if self._is_playing:
                    self._schedule_hide_player_chrome(3000)
            elif event.type() == QEvent.Type.Leave and self._is_playing:
                self._schedule_hide_player_chrome(3000)
        return super().eventFilter(watched, event)

    def _load_playlist_item(self, item: PlaylistItem) -> None:
        if not item.is_url and not Path(item.source).exists():
            self.osd.show_message(f"File not found: {item.title}", "warning")
            self._play_next()
            return
        self.title_bar.set_title(item.title)
        self._cover_mode = False
        self.control_bar.set_cover_mode(False)
        self.settings.set("playback.cover_mode", False)
        resume = self.history.resume_position(item.source) if self.settings.get("playback.remember_position", True) else 0.0
        self.player.load(item.source, resume)
        self.player.set_cover_mode(False)
        self.osd.show_message("Playing")
        QTimer.singleShot(250, self._position_overlays)

    def _time_changed(self, seconds: float) -> None:
        self._current_position = seconds
        self.control_bar.set_time(self._current_position, self._current_duration)

    def _duration_changed(self, seconds: float) -> None:
        self._current_duration = seconds
        self.control_bar.set_time(self._current_position, self._current_duration)

    def _tracks_changed(self, audio: list, subtitles: list) -> None:
        self.audio_tracks = audio
        self.subtitle_tracks = subtitles

    def _play_next(self) -> None:
        if self.playlist.next() is None:
            self.player.set_paused(True)

    def _play_previous(self) -> None:
        self.playlist.previous()

    def _play_resolved_url(self, original_url: str, resolved_url: str, title: str) -> None:
        item = PlaylistItem(resolved_url, title or original_url, True)
        self.playlist.clear()
        self.playlist.add_item(item)
        self.playlist.set_current(0)

    def _show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        actions = [
            ("Open File...", self._choose_files),
            ("Open URL...", lambda: self._show_url_dialog("")),
            ("Play/Pause", self.player.play_pause),
            ("Playlist", self._toggle_playlist),
            ("Screenshot", self._save_screenshot),
            ("Always on Top", self._toggle_always_on_top),
            ("Settings", self._show_settings),
        ]
        for label, callback in actions:
            action = QAction(label, menu)
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.exec(position)

    def _show_subtitle_menu(self) -> None:
        menu = self.track_menus.subtitle_menu(self.subtitle_tracks)
        load_action = menu.actions()[-1] if menu.actions() else None
        find_action = QAction("Find online...", menu)
        find_action.setData("__find_online__")
        if load_action is not None:
            menu.insertAction(load_action, find_action)
            menu.insertSeparator(load_action)
        else:
            menu.addAction(find_action)
        action = menu.exec(self.control_bar.subtitle_button.mapToGlobal(QPoint(0, 36)))
        if action is None:
            return
        data = action.data()
        if data == "__load_external__":
            path = self.track_menus.choose_subtitle_file()
            if path:
                self.player.load_subtitle(Path(path))
        elif data == "__find_online__":
            self._show_subtitle_finder()
        elif data is not None:
            self.player.set_subtitle_track(data)

    def _show_subtitle_finder(self) -> None:
        current = self.playlist.current_item()
        source = current.source if current is not None else ""
        dialog = SubtitleFinderDialog(source, self)
        dialog.subtitleSelected.connect(lambda path: self.player.load_subtitle(Path(path)))
        dialog.subtitleSelected.connect(lambda path: self.osd.show_message(f"Subtitle loaded: {Path(path).name}", "success"))
        dialog.exec()

    def _show_audio_menu(self) -> None:
        menu = self.track_menus.audio_menu(self.audio_tracks)
        action = menu.exec(self.control_bar.audio_button.mapToGlobal(QPoint(0, 36)))
        if action is not None and action.data() is not None:
            self.player.set_audio_track(action.data())

    def _show_url_dialog(self, initial_url: str) -> None:
        dialog = OpenUrlDialog(initial_url, self)
        dialog.urlAccepted.connect(self.open_url)
        dialog.exec()

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)))

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media", str(self.settings.get("paths.last_open_dir", Path.home())))
        if files:
            self.settings.set("paths.last_open_dir", str(Path(files[0]).parent))
            self.open_files([Path(path) for path in files], append=False)

    def _save_screenshot(self) -> None:
        directory = Path(str(self.settings.get("paths.screenshot_dir", Path.home() / "Desktop")))
        if not directory.exists() or not directory.is_dir():
            directory = Path.home() / "Desktop"
        filename = f"CometPlayer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output = directory / filename
        if self.player.screenshot(output):
            self.osd.show_message(f"Screenshot saved: {filename}", "success")
        else:
            self.osd.show_message("Screenshot failed", "error")

    def _cycle_ab_loop(self) -> None:
        if self._ab_a is None:
            self._ab_a = self._current_position
            self.control_bar.set_ab_state(f"A: {format_time(self._ab_a)} - Click to set B", True)
        elif self._ab_b is None:
            self._ab_b = max(self._current_position, self._ab_a + 1)
            self.player.set_ab_loop(self._ab_a, self._ab_b)
            self.control_bar.set_ab_state(f"A-B: {format_time(self._ab_a)} - {format_time(self._ab_b)}", True)
        else:
            self._ab_a = None
            self._ab_b = None
            self.player.set_ab_loop(None, None)
            self.control_bar.set_ab_state("Set A-B loop", False)

    def _handle_video_scroll(self, delta: int) -> None:
        if delta == 0:
            self.player.toggle_mute()
        else:
            self.player.change_volume(delta)

    def _handle_key(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Space:
            self.player.play_pause()
        elif key == Qt.Key.Key_Left:
            self.player.seek_relative(-5)
        elif key == Qt.Key.Key_Right:
            self.player.seek_relative(5)
        elif key == Qt.Key.Key_Up:
            self.player.change_volume(5)
        elif key == Qt.Key.Key_Down:
            self.player.change_volume(-5)
        elif key == Qt.Key.Key_M:
            self.player.toggle_mute()
        elif key == Qt.Key.Key_Control:
            self._toggle_mini_mode()
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if not self.isFullScreen():
                self._toggle_fullscreen()
        elif key == Qt.Key.Key_F:
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_C:
            self._toggle_cover_mode()
        elif key == Qt.Key.Key_Escape:
            self._pause_and_minimize()
        elif key == Qt.Key.Key_P:
            self._toggle_playlist()
        elif key == Qt.Key.Key_T:
            self._toggle_always_on_top()
        elif key == Qt.Key.Key_S:
            self._save_screenshot()
        elif key == Qt.Key.Key_O and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._choose_files()
        elif key == Qt.Key.Key_U and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._show_url_dialog("")
        elif key == Qt.Key.Key_Period:
            self._play_next()
        elif key == Qt.Key.Key_Comma:
            self._play_previous()

    def _toggle_fullscreen(self) -> None:
        if self._mini_mode:
            self._exit_mini_mode()
        if self.isFullScreen():
            self.showNormal()
            self.control_bar.set_fullscreen(False)
            self.unsetCursor()
        else:
            self.showFullScreen()
            self.control_bar.set_fullscreen(True)
        self._show_player_chrome()
        if self._is_playing:
            self._schedule_hide_player_chrome(3000)
        self._position_overlays()

    def _pause_and_minimize(self) -> None:
        self.player.set_paused(True)
        self.showMinimized()

    def _toggle_mini_mode(self) -> None:
        if self._mini_mode:
            self._exit_mini_mode()
        else:
            self._enter_mini_mode()

    def _enter_mini_mode(self) -> None:
        if self._mini_mode:
            return
        self._mini_mode = True
        self._hide_chrome_timer.stop()
        self._pre_mini_geometry = self.geometry()
        self._pre_mini_fullscreen = self.isFullScreen()
        self._pre_mini_maximized = self.isMaximized()
        self.playlist_panel.hide()
        self.control_bar.set_playlist_visible(False)
        self.setMinimumSize(420, TITLE_BAR_HEIGHT + CONTROL_BAR_HEIGHT)
        self.setMaximumHeight(16777215)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.showNormal()
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QRect(0, 0, DEFAULT_WINDOW_SIZE[0], TITLE_BAR_HEIGHT + CONTROL_BAR_HEIGHT)
        self.setGeometry(available.left(), available.top(), available.width(), TITLE_BAR_HEIGHT + CONTROL_BAR_HEIGHT)
        self.control_bar.set_fullscreen(False)
        self._chrome_visible = True
        self._position_overlays()
        self.raise_()
        self.activateWindow()

    def _exit_mini_mode(self) -> None:
        if not self._mini_mode:
            return
        self._mini_mode = False
        self.setMaximumHeight(16777215)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(self.settings.get("window.always_on_top", False)))
        if self._pre_mini_fullscreen:
            self.showFullScreen()
            self.control_bar.set_fullscreen(True)
        elif self._pre_mini_maximized:
            self.showMaximized()
            self.control_bar.set_fullscreen(False)
        else:
            self.showNormal()
            if self._pre_mini_geometry.isValid():
                self.setGeometry(self._pre_mini_geometry)
            self.control_bar.set_fullscreen(False)
        if self.settings.get("ui.show_playlist", False):
            self.playlist_panel.show()
            self.control_bar.set_playlist_visible(True)
        self._show_player_chrome()
        if self._is_playing:
            self._schedule_hide_player_chrome(3000)
        self._position_overlays()

    def _toggle_cover_mode(self) -> None:
        self._cover_mode = not self._cover_mode
        self.player.set_cover_mode(self._cover_mode)
        self.control_bar.set_cover_mode(self._cover_mode)
        self.settings.set("playback.cover_mode", self._cover_mode)
        self.osd.show_message("Video Mode: Cover Screen" if self._cover_mode else "Video Mode: Fit Screen")

    def _toggle_maximized(self) -> None:
        if self._mini_mode:
            self._exit_mini_mode()
        self.showNormal() if self.isMaximized() else self.showMaximized()
        self.title_bar.set_maximized(self.isMaximized())
        self._position_overlays()

    def _toggle_playlist(self) -> None:
        if self._mini_mode:
            return
        visible = not self.playlist_panel.isVisible()
        self.playlist_panel.setVisible(visible)
        self.control_bar.set_playlist_visible(visible)
        self.settings.set("ui.show_playlist", visible)
        self._position_overlays()

    def _toggle_pip(self) -> None:
        if self.pip_window is None:
            self.pip_window = PiPWindow(self)
            self.pip_window.show()
            self.osd.show_message("Picture in Picture: On")
        else:
            self.pip_window.close()
            self.pip_window = None
            self.osd.show_message("Picture in Picture: Off")

    def _toggle_always_on_top(self) -> None:
        self._apply_always_on_top(not bool(self.settings.get("window.always_on_top", False)))

    def _apply_always_on_top(self, enabled: bool, announce: bool = True) -> None:
        was_visible = self.isVisible()
        was_maximized = self.isMaximized()
        was_fullscreen = self.isFullScreen()
        self.settings.set("window.always_on_top", enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            if was_fullscreen:
                self.showFullScreen()
            elif was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
        if announce:
            self.osd.show_message(f"Always on Top: {'On' if enabled else 'Off'}")

    def _refresh_playlist(self) -> None:
        self.playlist_panel.refresh(self.playlist.items, self.playlist.current_index)

    def _show_controls(self) -> None:
        self._show_player_chrome()
        if self._is_playing and not self._mini_mode:
            self._schedule_hide_player_chrome(3000)
        if self.isFullScreen():
            self.unsetCursor()

    def _playback_state_changed(self, paused: bool) -> None:
        self._is_playing = not paused
        self._show_player_chrome()
        if paused or self._mini_mode:
            self._hide_chrome_timer.stop()
        else:
            self._schedule_hide_player_chrome(3000)

    def _handle_video_mouse_position(self, point: QPoint) -> None:
        if not self._is_playing or self._mini_mode:
            return
        reveal_zone = 48
        near_top = point.y() <= reveal_zone
        near_bottom = point.y() >= max(0, self.video.height() - reveal_zone)
        if near_top or near_bottom:
            self._show_player_chrome()
            self._schedule_hide_player_chrome(3000)
        elif self._chrome_visible:
            self._schedule_hide_player_chrome(3000)

    def _schedule_hide_player_chrome(self, delay_ms: int) -> None:
        if self._mini_mode:
            return
        if self.settings.get("ui.hide_controls_while_playing", True):
            self._hide_chrome_timer.start(delay_ms)

    def _show_player_chrome(self) -> None:
        self._animate_player_chrome(True)

    def _hide_player_chrome(self) -> None:
        if self._is_playing and not self._mini_mode:
            self._animate_player_chrome(False)

    def _animate_player_chrome(self, show: bool) -> None:
        if self.central_shell is None or self.isMinimized():
            return
        if self._mini_mode:
            self._chrome_visible = True
            self.title_bar.show()
            self.control_bar.show()
            self.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.title_bar.raise_()
            self.control_bar.raise_()
            self._position_overlays()
            return
        if self._chrome_visible == show and self._chrome_animation is None:
            return
        if self._chrome_animation is not None:
            self._chrome_animation.stop()
        self._chrome_visible = show
        shell_rect = self.central_shell.rect()
        start_title = self.title_bar.geometry()
        start_control = self.control_bar.geometry()
        if not start_title.isValid() or start_title.width() != shell_rect.width():
            start_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        if not start_control.isValid() or start_control.width() != shell_rect.width():
            y = shell_rect.height() - CONTROL_BAR_HEIGHT if show else shell_rect.height()
            start_control = QRect(0, y, shell_rect.width(), CONTROL_BAR_HEIGHT)
        target_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        target_control = QRect(0, shell_rect.height() - CONTROL_BAR_HEIGHT if show else shell_rect.height(), shell_rect.width(), CONTROL_BAR_HEIGHT)
        self.title_bar.show()
        self.control_bar.show()
        self.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
        self.title_bar.raise_()
        self.control_bar.raise_()
        self.title_bar.opacity.setOpacity(1.0)
        self.control_bar.opacity.setOpacity(1.0)
        group = QParallelAnimationGroup(self)
        for widget, start, target in ((self.title_bar, start_title, target_title), (self.control_bar, start_control, target_control)):
            animation = QPropertyAnimation(widget, b"geometry", group)
            animation.setDuration(180 if show else 220)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic if show else QEasingCurve.Type.InCubic)
            animation.setStartValue(start)
            animation.setEndValue(target)
            group.addAnimation(animation)

        def finish() -> None:
            if not show:
                self.title_bar.hide()
                self.control_bar.hide()
            else:
                self.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.title_bar.raise_()
                self.control_bar.raise_()
            self._chrome_animation = None

        group.finished.connect(finish)
        self._chrome_animation = group
        group.start()

    def _position_overlays(self) -> None:
        if self.central_shell is not None:
            shell_rect = self.central_shell.rect()
            self.video.setGeometry(shell_rect)
            if self._chrome_animation is None:
                if self._mini_mode:
                    title_y = 0
                    control_y = TITLE_BAR_HEIGHT
                    self._chrome_visible = True
                else:
                    title_y = 0 if self._chrome_visible else -TITLE_BAR_HEIGHT
                    control_y = shell_rect.height() - CONTROL_BAR_HEIGHT if self._chrome_visible else shell_rect.height()
                self.title_bar.setGeometry(0, title_y, shell_rect.width(), TITLE_BAR_HEIGHT)
                self.control_bar.setGeometry(0, control_y, shell_rect.width(), CONTROL_BAR_HEIGHT)
                self.title_bar.setVisible((self._chrome_visible or self._mini_mode) and not self.isMinimized())
                self.control_bar.setVisible((self._chrome_visible or self._mini_mode) and not self.isMinimized())
                if self._chrome_visible and not self.isMinimized():
                    self.title_bar.raise_()
                    self.control_bar.raise_()
        rect = self.video.rect()
        self.playlist_panel.setGeometry(max(0, rect.width() - PLAYLIST_PANEL_WIDTH), 0, PLAYLIST_PANEL_WIDTH, rect.height())
        self.drop_overlay.setGeometry(rect)
        if self.osd.isVisible():
            self.osd.adjustSize()
            self.osd.move((rect.width() - self.osd.width()) // 2, max(56, rect.height() // 2 - 28))

    def _start_window_drag(self, global_pos: QPoint) -> None:
        if self.isMaximized():
            return
        self._drag_start = global_pos
        self._window_start = self.frameGeometry().topLeft()

    def _move_window_drag(self, global_pos: QPoint) -> None:
        if self._drag_start is not None and self._window_start is not None and not self.isMaximized():
            self.move(self._window_start + global_pos - self._drag_start)

    def _restore_geometry(self) -> None:
        width = int(self.settings.get("window.width", DEFAULT_WINDOW_SIZE[0]))
        height = int(self.settings.get("window.height", DEFAULT_WINDOW_SIZE[1]))
        self.resize(max(width, MIN_WINDOW_SIZE[0]), max(height, MIN_WINDOW_SIZE[1]))
        x_value = self.settings.get("window.x")
        y_value = self.settings.get("window.y")
        if x_value is not None and y_value is not None:
            self.move(self._safe_window_position(int(x_value), int(y_value), self.width(), self.height()))
        if self.settings.get("window.maximized", False):
            self.showMaximized()
        if self.settings.get("ui.show_playlist", False):
            self.playlist_panel.show()
            self.control_bar.set_playlist_visible(True)

    def _show_startup_window(self) -> None:
        if self.settings.get("window.maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._position_overlays()

    def _safe_window_position(self, x: int, y: int, width: int, height: int) -> QPoint:
        if x <= -30000 or y <= -30000:
            return QPoint(80, 80)
        screens = QApplication.screens() or [QApplication.primaryScreen()]
        window_rect = QRect(x, y, max(width, MIN_WINDOW_SIZE[0]), max(height, MIN_WINDOW_SIZE[1]))
        for screen in screens:
            if screen is not None and screen.availableGeometry().intersects(window_rect):
                return QPoint(x, y)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QRect(0, 0, *DEFAULT_WINDOW_SIZE)
        safe_x = min(max(x, available.left()), max(available.left(), available.right() - width + 1))
        safe_y = min(max(y, available.top()), max(available.top(), available.bottom() - height + 1))
        return QPoint(safe_x, safe_y)

    def _save_geometry(self) -> None:
        if self._mini_mode:
            self.settings.set("window.maximized", self._pre_mini_maximized)
            geometry = self._pre_mini_geometry
            if geometry.isValid() and not self._pre_mini_fullscreen:
                self.settings.set("window.width", geometry.width())
                self.settings.set("window.height", geometry.height())
                self.settings.set("window.x", geometry.x())
                self.settings.set("window.y", geometry.y())
            return
        self.settings.set("window.maximized", self.isMaximized())
        if not self.isMaximized() and not self.isFullScreen():
            geometry = self.geometry()
            self.settings.set("window.width", geometry.width())
            self.settings.set("window.height", geometry.height())
            self.settings.set("window.x", geometry.x())
            self.settings.set("window.y", geometry.y())

    def _handle_window_edge_event(self, watched: object, event: QEvent) -> bool:
        if self.isMaximized() or self.isFullScreen() or self.isMinimized():
            return False
        if not isinstance(watched, QWidget):
            return False
        if watched is not self and not self.isAncestorOf(watched):
            return False
        event_type = event.type()
        if event_type not in {QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.Leave}:
            return False
        if event_type == QEvent.Type.Leave:
            if not self._resize_edge:
                self.unsetCursor()
            return False
        point = self.mapFromGlobal(QCursor.pos())
        if event_type == QEvent.Type.MouseMove:
            if self._resize_edge:
                self._perform_resize(QCursor.pos())
                return True
            self._update_resize_cursor(point)
            return False
        if event_type == QEvent.Type.MouseButtonPress:
            if getattr(event, "button", lambda: None)() != Qt.MouseButton.LeftButton:
                return False
            edge = self._edge_at(point)
            if not edge:
                return False
            self._resize_edge = edge
            self._resize_geometry = self.geometry()
            self._resize_start = QCursor.pos()
            return True
        if event_type == QEvent.Type.MouseButtonRelease and self._resize_edge:
            self._resize_edge = ""
            self._update_resize_cursor(point)
            return True
        return False

    def _edge_at(self, point: QPoint) -> str:
        margin = 8
        rect = self.rect()
        left = point.x() <= margin
        right = point.x() >= rect.width() - margin
        top = point.y() <= margin
        bottom = point.y() >= rect.height() - margin
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _update_resize_cursor(self, point: QPoint) -> None:
        edge = self._edge_at(point)
        cursor = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }.get(edge, Qt.CursorShape.ArrowCursor)
        self.setCursor(QCursor(cursor))

    def _perform_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_start
        geo = QRect(self._resize_geometry)
        if "left" in self._resize_edge:
            geo.setLeft(geo.left() + delta.x())
        if "right" in self._resize_edge:
            geo.setRight(geo.right() + delta.x())
        if "top" in self._resize_edge:
            geo.setTop(geo.top() + delta.y())
        if "bottom" in self._resize_edge:
            geo.setBottom(geo.bottom() + delta.y())
        min_width, min_height = self._resize_minimum_size()
        if geo.width() >= min_width and geo.height() >= min_height:
            self.setGeometry(geo)

    def _resize_minimum_size(self) -> tuple[int, int]:
        if self._mini_mode:
            return 420, TITLE_BAR_HEIGHT + CONTROL_BAR_HEIGHT
        return MIN_WINDOW_SIZE
