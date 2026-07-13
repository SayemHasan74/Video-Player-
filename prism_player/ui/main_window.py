"""Root application window and component controller."""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QRect, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QCursor, QDragEnterEvent, QDropEvent, QIcon, QKeyEvent, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMenuBar, QWidget

from config.settings import APP_NAME, CONTROL_BAR_HEIGHT, DEFAULT_WINDOW_SIZE, MIN_WINDOW_SIZE, SettingsStore, TITLE_BAR_HEIGHT, global_stylesheet
from core.history_manager import HistoryManager
from core.filter_store import FilterStore
from core.keybindings import KeyBindingStore
from core.player_backend import PlayerBackend
from core.playlist_manager import PlaylistItem, PlaylistManager
from core.url_resolver import UrlResolverWorker
from ui.control_bar import ControlBar
from ui.crop_overlay import CropSelectionOverlay
from ui.input_controller import PlayerInputController
from ui.auxiliary_windows import HistoryWindow, InspectorWindow, PreferencesWindow, WelcomeWindow
from ui.filter_window import FiltersWindow
from ui.open_url_dialog import OpenUrlDialog
from ui.osd import OSDLabel
from ui.overlay_controller import OverlayController
from ui.playlist_panel import PlaylistPanel
from ui.subtitle_finder_dialog import SubtitleFinderDialog
from ui.title_bar import TitleBar
from ui.track_menu import TrackMenuFactory
from ui.video_widget import VideoWidget
from ui.window_mode import WindowMode, WindowModeController
from utils.file_utils import is_media_file, is_probable_url, scan_media_files
from core.media_probe import matching_subtitles
from utils.time_utils import format_time
from utils.thumbnail import ThumbnailWorker, trim_thumbnail_cache

APP_MENU_HEIGHT = 32
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
        self.key_store=KeyBindingStore(); self.filter_store=FilterStore(); self._binding_shortcuts:list[QShortcut]=[]; self._filter_shortcuts:list[QShortcut]=[]; self._menu_actions:dict[str,QAction]={}; self._key_profile_actions:dict[str,QAction]={}; self._key_profile_menu:QMenu|None=None
        self.video = VideoWidget(self)
        self.crop_overlay = CropSelectionOverlay(self.video)
        self.title_bar = TitleBar(self)
        self.control_bar = ControlBar(self)
        self.playlist_panel = PlaylistPanel(self)
        self.osd = OSDLabel(self.video)
        self.drop_overlay = QLabel("Drop to play", self.video)
        self.buffering_indicator = QLabel("Buffering…", self.video)
        self.buffering_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.buffering_indicator.setStyleSheet("background: rgba(0,0,0,180); color: white; border-radius: 18px; padding: 10px 16px;")
        self.buffering_indicator.hide()
        self.thumbnail_preview = QLabel(self.video); self.thumbnail_preview.setStyleSheet("background:#080808;border:1px solid #444;padding:3px;"); self.thumbnail_preview.hide()
        self.track_menus = TrackMenuFactory(self)
        self.welcome_window: WelcomeWindow | None = None
        self.history_window: HistoryWindow | None = None
        self.filters_window: FiltersWindow | None = None
        self.inspector_window: InspectorWindow | None = None
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
        self.overlays = OverlayController(self)
        self.window_modes = WindowModeController(self)
        self.inputs = PlayerInputController(self)
        self.central_shell: QWidget | None = None
        self.app_menu_bar: QMenuBar | None = None
        self._current_duration = 0.0
        self._current_position = 0.0
        self._loaded_playlist_item: PlaylistItem | None = None
        self._thumbnail_worker: ThumbnailWorker | None = None
        self._thumbnails: dict[float,str] = {}
        self._thumbnail_signature: tuple[str,int] | None = None
        self._build_window()
        self.osd.set_enabled(bool(self.settings.get("ui.show_osd", True)))
        self.player = PlayerBackend(self.video, self)
        self._apply_player_preferences()
        for preset in self.filter_store.load():
            if preset.get("enabled"):
                self.player.add_filter(preset["kind"], preset["value"])
        self._build_app_menu()
        self._load_keybindings()
        self._position_overlays()
        self._connect_signals()
        self._restore_geometry()
        self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)), announce=False)
        self._apply_ui_preferences()
        self._show_startup_window()
        if startup_files:
            self.open_files(startup_files, append=False)
        elif self.settings.get("startup.reopen_last", False) and self.settings.get("startup.last_source", ""):
            last_source = str(self.settings.get("startup.last_source", ""))
            if is_probable_url(last_source):
                self.open_url(last_source)
            elif Path(last_source).exists():
                self.open_files([Path(last_source)], append=False)
        elif self.settings.get("startup.show_welcome", True):
            QTimer.singleShot(0, self._show_welcome)

    @property
    def _mini_mode(self) -> bool:
        return self.window_modes.is_compact

    @property
    def _pip_mode(self) -> bool:
        return self.window_modes.is_pip

    def open_files(self, files: list[Path], append: bool = False) -> None:
        """Add files to the playlist and start playback."""
        media = [path for path in files if is_media_file(path)]
        if not media:
            self.osd.show_message("No supported media files found", "warning")
            return
        selected_index = 0
        # When a single file is opened (including through Explorer), make its
        # containing folder the playlist.  This also gives Next/Previous the
        # neighbouring media files users expect.
        if not append and len(media) == 1 and media[0].is_file():
            selected = media[0].resolve()
            siblings = scan_media_files([selected.parent])
            if siblings:
                media = siblings
                selected_index = next(
                    (index for index, path in enumerate(media) if path.resolve() == selected),
                    0,
                )
        self.playlist.add_sources(media, append=append)
        if not append or self.playlist.current_index == -1:
            self.playlist.set_current(selected_index)
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
            if self.app_menu_bar is not None: self.app_menu_bar.hide()
            self.title_bar.hide()
            self.control_bar.hide()
        else:
            self.window_modes.sync_from_window()
            self._apply_mode_layout()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        current = self.playlist.current_item()
        if current is not None and self.settings.get("playback.remember_position", True):
            self.history.save_position(current.source, current.title, self._current_position, self._current_duration)
        self.settings.set("startup.last_source", current.source if current is not None else "")
        self.settings.set("playback.volume", self.control_bar.volume.slider.value())
        self.settings.save()
        self.playlist_panel.shutdown()
        if self._thumbnail_worker and self._thumbnail_worker.isRunning():
            self._thumbnail_worker.cancel(); self._thumbnail_worker.wait(2000)
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
        self.playlist_panel.setParent(central)
        for chrome in (self.title_bar, self.control_bar):
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
        self.video.doubleClicked.connect(self._toggle_fullscreen)
        self.video.clicked.connect(self._video_clicked)
        self.video.rightClicked.connect(self._show_context_menu)
        self.video.middleClicked.connect(self._toggle_mini_mode)
        self.video.scrolled.connect(self._handle_video_scroll)
        self.video.mouseMoved.connect(self._show_controls)
        self.video.mousePositionChanged.connect(self._handle_video_mouse_position)
        self.video.keyPressed.connect(self._handle_key)
        self.control_bar.playPauseClicked.connect(self.player.play_pause)
        self.control_bar.stopClicked.connect(self.player.stop)
        self.control_bar.nextClicked.connect(self._play_next)
        self.control_bar.previousClicked.connect(self._play_previous)
        self.control_bar.seekRequested.connect(self.player.seek_absolute)
        self.control_bar.seekbar.hoverRequested.connect(self._show_thumbnail_preview)
        self.control_bar.seekbar.hoverEnded.connect(self.thumbnail_preview.hide)
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
        self.playlist_panel.addRequested.connect(self._choose_files)
        self.playlist_panel.chapterActivated.connect(self.player.seek_absolute)
        self.playlist_panel.quickSettingChanged.connect(self._apply_quick_setting)
        self.playlist_panel.quick_settings.findSubtitles.connect(self._show_subtitle_finder)
        self.playlist_panel.quick_settings.cropSelectionRequested.connect(self.crop_overlay.begin)
        self.crop_overlay.selectionFinished.connect(self._crop_selection_finished)
        self.playlist_panel.moveRequested.connect(self.playlist.move)
        self.playlist_panel.sortRequested.connect(self.playlist.sort_items)
        self.playlist_panel.playNextRequested.connect(self._queue_playlist_item_next)
        self.playlist_panel.widthChanged.connect(self._sidebar_width_changed)
        self.playlist_panel.tabChanged.connect(lambda name: self.settings.set("ui.sidebar_tab", name))
        self.playlist_panel.keyPressed.connect(self._handle_key)
        self.player.timeChanged.connect(self._time_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.pauseStateChanged.connect(self.control_bar.set_paused)
        self.player.pauseStateChanged.connect(self._playback_state_changed)
        self.player.volumeChanged.connect(self.control_bar.set_volume_state)
        self.player.speedChanged.connect(self.control_bar.set_speed)
        self.player.tracksChanged.connect(self._tracks_changed)
        self.player.chaptersChanged.connect(self.playlist_panel.set_chapters)
        self.player.bufferingChanged.connect(self.buffering_indicator.setVisible)
        self.player.fileEnded.connect(self._play_next)
        self.player.error.connect(lambda text: self.osd.show_message(text, "error"))
        self.player.stateChanged.connect(self.playlist_panel.quick_settings.set_state)
        self.control_bar.set_cover_mode(self._cover_mode)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            app.installEventFilter(self.inputs)
        self.video.installEventFilter(self)
        self.title_bar.installEventFilter(self)
        self.control_bar.installEventFilter(self)
        QShortcut(Qt.Key.Key_Return, self, activated=lambda: None if self.isFullScreen() else self._toggle_fullscreen())
        QShortcut(Qt.Key.Key_Enter, self, activated=lambda: None if self.isFullScreen() else self._toggle_fullscreen())
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste_playlist_content)
        paste_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)

    def _build_app_menu(self) -> None:
        bar = QMenuBar(self.central_shell)
        self.app_menu_bar = bar
        bar.setNativeMenuBar(False)
        bar.setStyleSheet("QMenuBar { background: #0d0d0d; color: #eeeeee; padding-left: 6px; } QMenuBar::item { padding: 7px 10px; background: transparent; } QMenuBar::item:selected { background: #242424; }")
        menus = {
            "File": [("Open File…","open_file",self._choose_files),("Open URL…","open_url",lambda:self._show_url_dialog("")),("History","history",self._show_history),("Screenshot","screenshot",self._save_screenshot),("Quit","quit",self.close)],
            "Playback": [("Play/Pause","play_pause",self.player.play_pause),("Stop","stop",self.player.stop),("Previous","previous",self._play_previous),("Next","next",self._play_next),("A–B Loop","ab_loop",self._cycle_ab_loop)],
            "Video": [("Fullscreen","fullscreen",self._toggle_fullscreen),("Fit/Cover","cover",self._toggle_cover_mode),("Select Crop…","crop_select",self.crop_overlay.begin),("Filters","filters",self._show_filters),("Inspector","inspector",self._show_inspector)],
            "Audio": [("Audio Tracks","audio_tracks",self._show_audio_menu),("Mute","mute",self.player.toggle_mute)],
            "Subtitle": [("Subtitle Tracks","subtitle_tracks",self._show_subtitle_menu),("Hide/Show All","subtitle_visibility",self._toggle_subtitle_visibility),("Find Online…","find_subtitles",self._show_subtitle_finder)],
            "Window": [("Playlist","playlist",self._toggle_playlist),("Music Mode","music_mode",self._toggle_mini_mode),("Picture in Picture","pip",self._toggle_pip),("Always on Top","always_on_top",self._toggle_always_on_top),("Preferences","preferences",self._show_settings)],
            "Help": [("About Comet V2","about",lambda:self.osd.show_message("Comet V2 • IINA-inspired media player"))],
        }
        for title, entries in menus.items():
            menu = bar.addMenu(title)
            for label, action_id, callback in entries:
                action = QAction(label, self); action.triggered.connect(callback); menu.addAction(action); self._menu_actions[action_id]=action
            if title == "Window":
                self._key_profile_menu = menu.addMenu("Key Binding Profile")
                self._refresh_key_profile_menu()
        bar.raise_()

    def _action_callbacks(self) -> dict[str, object]:
        return {"play_pause":self.player.play_pause,"seek_backward":lambda:self.player.seek_relative(-5),"seek_forward":lambda:self.player.seek_relative(5),"volume_up":lambda:self.player.change_volume(5),"volume_down":lambda:self.player.change_volume(-5),"mute":self.player.toggle_mute,"fullscreen":self._toggle_fullscreen,"exit_fullscreen":self._pause_and_minimize,"playlist":self._toggle_playlist,"always_on_top":self._toggle_always_on_top,"screenshot":self._save_screenshot,"open_file":self._choose_files,"open_url":lambda:self._show_url_dialog(""),"next":self._play_next,"previous":self._play_previous,"music_mode":self._toggle_mini_mode,"pip":self._toggle_pip,"filters":self._show_filters,"inspector":self._show_inspector,"history":self._show_history,"preferences":self._show_settings,"find_subtitles":self._show_subtitle_finder}

    def _switch_key_profile(self, profile: str) -> None:
        self.settings.set("keys.profile", profile)
        self.settings.save()
        self._load_keybindings()
        for name, action in self._key_profile_actions.items(): action.setChecked(name == profile)
        self.osd.show_message(f"Key profile: {profile}")

    def _refresh_key_profile_menu(self) -> None:
        if self._key_profile_menu is None:
            return
        self._key_profile_menu.clear()
        self._key_profile_actions.clear()
        current = str(self.settings.get("keys.profile", "Default"))
        for name in self.key_store.profile_names():
            action = self._key_profile_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(lambda _checked=False, profile=name: self._switch_key_profile(profile))
            self._key_profile_actions[name] = action

    def _load_keybindings(self) -> None:
        for shortcut in self._binding_shortcuts:shortcut.setEnabled(False);shortcut.deleteLater()
        self._binding_shortcuts=[]; bindings=self.key_store.load(str(self.settings.get("keys.profile","Default"))); callbacks=self._action_callbacks(); reverse={}
        for key,action_id in bindings.items():
            callback=callbacks.get(action_id)
            if callback:
                reverse.setdefault(action_id,key)
                if QKeySequence(key).matches(QKeySequence(Qt.Key.Key_Space)) == QKeySequence.SequenceMatch.ExactMatch:
                    continue
                shortcut=QShortcut(QKeySequence(key),self,activated=callback);shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut);self._binding_shortcuts.append(shortcut)
        for action_id,action in self._menu_actions.items():action.setShortcut(QKeySequence(reverse.get(action_id,"")))
        self._load_filter_shortcuts()

    def _load_filter_shortcuts(self) -> None:
        for shortcut in self._filter_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._filter_shortcuts = []
        for index, preset in enumerate(self.filter_store.load()):
            sequence = str(preset.get("shortcut") or "")
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self, activated=lambda preset_index=index: self._toggle_saved_filter(preset_index))
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            self._filter_shortcuts.append(shortcut)

    def _toggle_saved_filter(self, index: int) -> None:
        presets = self.filter_store.load()
        if not 0 <= index < len(presets):
            return
        preset = presets[index]
        preset["enabled"] = not bool(preset.get("enabled"))
        operation = self.player.add_filter if preset["enabled"] else self.player.remove_filter
        operation(preset["kind"], preset["value"])
        self.filter_store.save(presets)
        self.osd.show_message(f"{preset['name']}: {'On' if preset['enabled'] else 'Off'}")

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
        previous=self._loaded_playlist_item
        if previous is not None and previous.source!=item.source and self.settings.get("playback.remember_position",True):
            self.history.save_position(previous.source,previous.title,self._current_position,self._current_duration)
        self._loaded_playlist_item=item
        self._current_position=0.0;self._current_duration=0.0
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
        if not item.is_url and self.settings.get("subtitle.autoload", True):
            for index, subtitle in enumerate(matching_subtitles(item.source)):
                self.player.load_subtitle(subtitle, select=index == 0, secondary=index == 1)
        if not item.is_url and Path(item.source).suffix.lower() in {".mp3", ".flac", ".aac", ".m4a", ".wav", ".ogg", ".opus", ".ape", ".aiff"} and self.settings.get("playback.auto_music_mode", True) and not self._mini_mode:
            QTimer.singleShot(200, self._enter_mini_mode)
        self.player.set_cover_mode(False)
        self.osd.show_message("Playing")

    def _time_changed(self, seconds: float) -> None:
        self._current_position = seconds
        self.control_bar.set_time(self._current_position, self._current_duration)
        current=self.playlist.current_item()
        if current: self.playlist_panel.update_progress(current.source,self._current_position,self._current_duration)

    def _duration_changed(self, seconds: float) -> None:
        self._current_duration = seconds
        self.control_bar.set_time(self._current_position, self._current_duration)
        current=self.playlist.current_item()
        if current and not current.is_url and seconds>0 and self.settings.get("thumbnails.enabled",True): self._start_thumbnails(current.source,seconds)

    def _start_thumbnails(self, source: str, duration: float) -> None:
        signature=(source,round(duration))
        if signature==self._thumbnail_signature:return
        self._thumbnail_signature=signature
        if self._thumbnail_worker and self._thumbnail_worker.isRunning(): self._thumbnail_worker.cancel(); self._thumbnail_worker.wait(500)
        self._thumbnails={}; trim_thumbnail_cache(int(self.settings.get("thumbnails.cache_mb",512)))
        self._thumbnail_worker=ThumbnailWorker(source,duration,int(self.settings.get("thumbnails.samples",100)),self); self._thumbnail_worker.thumbnailReady.connect(lambda timestamp,path:self._thumbnails.__setitem__(timestamp,path)); self._thumbnail_worker.start()

    def _show_thumbnail_preview(self, seconds: float, point: QPoint) -> None:
        if not self._thumbnails:return
        timestamp=min(self._thumbnails,key=lambda value:abs(value-seconds)); pixmap=QPixmap(self._thumbnails[timestamp])
        if pixmap.isNull():return
        pixmap=pixmap.scaledToWidth(240,Qt.TransformationMode.SmoothTransformation); self.thumbnail_preview.setPixmap(pixmap); self.thumbnail_preview.adjustSize(); global_point=self.control_bar.seekbar.mapToGlobal(point); local=self.video.mapFromGlobal(global_point); x=max(0,min(self.video.width()-self.thumbnail_preview.width(),local.x()-self.thumbnail_preview.width()//2)); y=max(0,self.video.height()-CONTROL_BAR_HEIGHT-self.thumbnail_preview.height()-12); self.thumbnail_preview.move(x,y); self.thumbnail_preview.show(); self.thumbnail_preview.raise_()

    def _tracks_changed(self, audio: list, subtitles: list) -> None:
        self.audio_tracks = audio
        self.subtitle_tracks = subtitles
        self.playlist_panel.quick_settings.set_tracks(audio, subtitles)

    def _play_next(self) -> None:
        if self.playlist.next() is None:
            self.player.set_paused(True)

    def _play_previous(self) -> None:
        self.playlist.previous()

    def _queue_playlist_item_next(self, index: int) -> None:
        if not 0 <= index < len(self.playlist.items): return
        item = self.playlist.items[index]
        self.playlist.remove(index)
        self.playlist.insert_next(item)

    def _play_resolved_url(self, original_url: str, resolved_url: str, title: str) -> None:
        item = PlaylistItem(resolved_url, title or original_url, True)
        self.playlist.clear()
        self.playlist.add_item(item)
        self.playlist.set_current(0)

    def _show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        groups = (
            ("open_file", "open_url"),
            ("play_pause", "stop", "previous", "next"),
            ("audio_tracks", "subtitle_tracks", "subtitle_visibility"),
            ("screenshot", "cover", "fullscreen"),
            ("playlist", "filters", "inspector"),
            ("pip", "music_mode", "always_on_top"),
            ("history", "preferences"),
        )
        for group_index, group in enumerate(groups):
            if group_index: menu.addSeparator()
            for action_id in group:
                action = self._menu_actions.get(action_id)
                if action is not None: menu.addAction(action)
        menu.exec(position)

    def _toggle_subtitle_visibility(self) -> None:
        visible = bool(self.player.get_property("sub-visibility", True))
        self.player.set_property("sub-visibility", not visible)
        self.osd.show_message(f"Subtitles: {'On' if not visible else 'Hidden'}")

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
        dialog = PreferencesWindow(self.settings, self.history, self)
        if dialog.exec():
            self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)))
            self._apply_player_preferences()
            self._apply_ui_preferences()
            self.osd.set_enabled(bool(self.settings.get("ui.show_osd", True)))
            self.playlist_panel.set_side(str(self.settings.get("ui.sidebar_side", "right")))
            self.playlist_panel.set_current_tab(str(self.settings.get("ui.sidebar_tab", "playlist")))
            if not self.settings.get("ui.hide_controls_while_playing", True):
                self.overlays.hide_timer.stop(); self._show_player_chrome()
            self._load_keybindings()
            self._refresh_key_profile_menu()

    def _apply_player_preferences(self) -> None:
        """Apply settings that mpv can change safely during the current session."""
        self.player.set_volume(int(self.settings.get("playback.volume", 80)))
        self.player.set_muted(bool(self.settings.get("playback.muted", False)))
        self.player.set_speed(float(self.settings.get("playback.speed", 1.0)))
        properties = {
            "hwdec": self.settings.get("video.hwdec", "auto-safe"),
            "video-aspect-override": "no" if self.settings.get("video.aspect", "auto") == "auto" else self.settings.get("video.aspect", "auto"),
            "audio-device": self.settings.get("audio.device", "auto"),
            "gapless-audio": "yes" if self.settings.get("audio.gapless", False) else "no",
            "sub-font": self.settings.get("subtitle.font", "Segoe UI"),
            "sub-font-size": self.settings.get("subtitle.size", 42),
            "sub-color": self.settings.get("subtitle.color", "#ffffff"),
            "sub-border-size": self.settings.get("subtitle.outline", 2),
            "sub-pos": self.settings.get("subtitle.position", 100),
            "sub-codepage": self.settings.get("subtitle.encoding", "auto"),
        }
        proxy = str(self.settings.get("network.proxy", "")).strip()
        user_agent = str(self.settings.get("network.user_agent", "")).strip()
        if proxy: properties["http-proxy"] = proxy
        if user_agent: properties["user-agent"] = user_agent
        for name, value in properties.items():
            self.player.set_property(name, value)
        raw_options = str(self.settings.get("advanced.mpv_options", ""))
        for entry in raw_options.replace(";", "\n").splitlines():
            name, separator, value = entry.strip().partition("=")
            if name and separator:
                self.player.set_property(name.strip(), value.strip())

    def _apply_ui_preferences(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(global_stylesheet() if self.settings.get("ui.theme", "dark") == "dark" else "")
        self._position_overlays()

    def _paste_playlist_content(self) -> None:
        """Queue local files/folders or open a URL copied to the clipboard."""
        mime = QApplication.clipboard().mimeData()
        paths: list[Path] = []
        urls: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile(): paths.append(Path(url.toLocalFile()))
                elif is_probable_url(url.toString()): urls.append(url.toString())
        if mime.hasText() and not paths and not urls:
            for line in mime.text().splitlines():
                text = line.strip().strip('"')
                if not text: continue
                if is_probable_url(text): urls.append(text)
                else:
                    path = Path(text).expanduser()
                    if path.exists(): paths.append(path)
        folders = [path for path in paths if path.is_dir()]
        files = [path for path in paths if path.is_file()]
        if folders:
            self.folder_worker = FolderScanWorker(folders, False, self)
            self.folder_worker.scanned.connect(lambda found: self.open_files(found, append=True)); self.folder_worker.start()
        if files: self.open_files(files, append=True)
        if urls: self.open_url(urls[0])
        if paths or urls: self.osd.show_message("Added from clipboard", "success")

    def _sidebar_width_changed(self, width: int) -> None:
        self.settings.set("ui.sidebar_width", int(width))
        self._position_overlays()

    def _show_welcome(self) -> None:
        if self.playlist.current_item() is not None:
            return
        self.welcome_window = WelcomeWindow(self.history, str(self.settings.get("startup.last_source", "")), self)
        self.welcome_window.openFiles.connect(lambda files: (self.open_files(files, False), self.welcome_window.close()))
        self.welcome_window.openUrl.connect(lambda url: self.open_url(url) if url else self._show_url_dialog(""))
        self.welcome_window.show()

    def _show_history(self) -> None:
        self.history_window = HistoryWindow(self.history, self)
        self.history_window.openSource.connect(lambda source: self.open_url(source) if is_probable_url(source) else self.open_files([Path(source)], False))
        self.history_window.show()

    def _show_inspector(self) -> None:
        current = self.playlist.current_item()
        if current is None:
            return
        self.inspector_window = InspectorWindow(self.player, current.source, self)
        self.inspector_window.show()

    def _show_filters(self) -> None:
        self.filters_window = FiltersWindow(self, self.filter_store)
        self.filters_window.applyFilter.connect(self.player.add_filter)
        self.filters_window.removeFilter.connect(self.player.remove_filter)
        self.player.filtersChanged.connect(self.filters_window.set_active_filters)
        self.filters_window.savedFiltersChanged.connect(self._load_filter_shortcuts)
        self.filters_window.set_active_filters(
            self.player.get_property("vf", []) or [],
            self.player.get_property("af", []) or [],
        )
        self.filters_window.show()

    def _apply_quick_setting(self, key: str, value: object) -> None:
        if key == "crop":
            if isinstance(value, dict) and value.get("w") and value.get("h"):
                crop = f"crop={value['w']}:{value['h']}:{value['x']}:{value['y']}"
                self.player.replace_filter("video", "comet_crop", crop)
            else:
                self.player.replace_filter("video", "comet_crop", None)
            return
        if key == "audio-eq":
            values = value if isinstance(value, dict) else {}
            filters = ",".join(
                f"equalizer=f={frequency}:width_type=o:width=1:g={gain}"
                for frequency, gain in values.items() if gain
            )
            self.player.replace_filter("audio", "comet_eq", f"lavfi=[{filters}]" if filters else None)
            return
        if key == "video-rotate": value = int(value)
        if key == "video-aspect-override" and value == "auto": value = "no"
        self.player.set_property(key, value)

    def _crop_selection_finished(self, selection: QRect) -> None:
        """Translate the displayed crop rectangle to source-video pixel coordinates."""
        params = self.player.get_property("video-params", {}) or {}
        source_width = int(params.get("w") or params.get("dw") or self.video.width())
        source_height = int(params.get("h") or params.get("dh") or self.video.height())
        if self.video.width() <= 0 or self.video.height() <= 0:
            return
        scale_x = source_width / self.video.width()
        scale_y = source_height / self.video.height()
        self.playlist_panel.quick_settings.set_crop(
            round(selection.width() * scale_x),
            round(selection.height() * scale_y),
            round(selection.x() * scale_x),
            round(selection.y() * scale_y),
        )

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media", str(self.settings.get("paths.last_open_dir", Path.home())))
        if files:
            self.settings.set("paths.last_open_dir", str(Path(files[0]).parent))
            paths = [Path(path) for path in files]
            behavior = str(self.settings.get("playback.open_behavior", "replace"))
            if behavior == "new_window":
                self._open_in_new_window(paths)
            else:
                self.open_files(paths, append=behavior == "append")

    def _open_in_new_window(self, paths: list[Path]) -> None:
        if getattr(sys, "frozen", False):
            command = [sys.executable, *map(str, paths)]
        else:
            command = [sys.executable, str(Path(__file__).resolve().parents[2] / "main.py"), *map(str, paths)]
        creation_flags = 0x00000008 if sys.platform == "win32" else 0
        subprocess.Popen(command, creationflags=creation_flags)

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
        self.inputs.handle_key(event)

    def _toggle_fullscreen(self) -> None:
        self.window_modes.toggle_fullscreen()
        if not self.isFullScreen():
            self.unsetCursor()
        self._show_player_chrome()
        if self._is_playing:
            self._schedule_hide_player_chrome(3000)

    def _pause_and_minimize(self) -> None:
        self.player.set_paused(True)
        self.showMinimized()

    def _toggle_mini_mode(self) -> None:
        self.window_modes.toggle_compact()

    def _enter_mini_mode(self) -> None:
        self.window_modes.enter_compact()

    def _exit_mini_mode(self) -> None:
        self.window_modes.exit_compact()

    def _prepare_mode_transition(self) -> None:
        """Stop transient UI work before one atomic window-state transition."""
        self.overlays.stop_transients()

    def _apply_mode_layout(self) -> None:
        """Apply chrome visibility for the controller's current explicit mode."""
        visible = self._chrome_visible and not self._pip_mode
        if self.app_menu_bar is not None:
            self.app_menu_bar.setVisible(visible)
        self.title_bar.setVisible(visible)
        self.control_bar.setVisible(visible)
        self.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not visible)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not visible)
        self._position_overlays()
        if visible:
            self.title_bar.raise_()
            if self.app_menu_bar is not None:
                self.app_menu_bar.raise_()
            self.control_bar.raise_()
        if self._is_playing and not self._mini_mode and not self._pip_mode:
            self._schedule_hide_player_chrome(3000)

    def _toggle_cover_mode(self) -> None:
        self._cover_mode = not self._cover_mode
        self.player.set_cover_mode(self._cover_mode)
        self.control_bar.set_cover_mode(self._cover_mode)
        self.settings.set("playback.cover_mode", self._cover_mode)
        self.osd.show_message("Video Mode: Cover Screen" if self._cover_mode else "Video Mode: Fit Screen")

    def _toggle_maximized(self) -> None:
        self.window_modes.toggle_maximized()

    def _toggle_playlist(self) -> None:
        if self._mini_mode:
            return
        self._set_playlist_visible(not self.playlist_panel.isVisible())

    def _set_playlist_visible(self, visible: bool) -> None:
        """Show or hide the playlist and keep its persisted UI state in sync."""
        self.playlist_panel.setVisible(visible)
        if visible:
            self.playlist_panel.raise_()
            self.title_bar.raise_()
            self.control_bar.raise_()
        self.control_bar.set_playlist_visible(visible)
        self.settings.set("ui.show_playlist", visible)
        self._position_overlays()

    def _is_playlist_widget(self, widget: QWidget | None) -> bool:
        """Return whether a clicked widget belongs to the playlist panel."""
        while widget is not None:
            if widget is self.playlist_panel:
                return True
            widget = widget.parentWidget()
        return False

    def _toggle_pip(self) -> None:
        self.window_modes.toggle_pip()
        self.raise_()
        self.activateWindow()
        self.osd.show_message(f"Picture in Picture: {'On' if self._pip_mode else 'Off'}")

    def _video_clicked(self) -> None:
        if self._pip_mode:
            self._toggle_pip()
        else:
            self._animate_player_chrome(not self._chrome_visible)

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
        history={entry["source"]:(float(entry["position"]),float(entry["duration"])) for entry in self.history.entries()}
        self.playlist_panel.refresh(self.playlist.items, self.playlist.current_index, history)

    def _show_controls(self) -> None:
        if self._pip_mode:
            return
        self._show_player_chrome()
        if self._is_playing and not self._mini_mode:
            self._schedule_hide_player_chrome(3000)
        if self.isFullScreen():
            self.unsetCursor()

    def _playback_state_changed(self, paused: bool) -> None:
        self._is_playing = not paused
        self._show_player_chrome()
        if paused or self._mini_mode:
            self.overlays.hide_timer.stop()
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
        self.overlays.schedule_hide(delay_ms)

    def _show_player_chrome(self) -> None:
        self.overlays.show()

    def _hide_player_chrome(self) -> None:
        self.overlays.hide()

    def _animate_player_chrome(self, show: bool) -> None:
        self.overlays.animate(show)

    def _position_overlays(self) -> None:
        self.overlays.position()
        self.crop_overlay.setGeometry(self.video.rect())

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
        compact_height = TITLE_BAR_HEIGHT + APP_MENU_HEIGHT + CONTROL_BAR_HEIGHT
        # Older compact-mode builds could persist the collapsed strip as the
        # normal geometry. Recover those installations on the next launch.
        if height <= compact_height:
            height = DEFAULT_WINDOW_SIZE[1]
            self.settings.set("window.height", height)
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
        self.playlist_panel.set_side(str(self.settings.get("ui.sidebar_side", "right")))
        self.playlist_panel.set_current_tab(str(self.settings.get("ui.sidebar_tab", "playlist")))

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
            snapshot = self.window_modes.compact_snapshot
            if snapshot is None:
                return
            self.settings.set("window.maximized", snapshot.mode is WindowMode.MAXIMIZED)
            geometry = snapshot.geometry
            if geometry.isValid() and snapshot.mode is WindowMode.NORMAL:
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
            return 420, TITLE_BAR_HEIGHT + APP_MENU_HEIGHT + CONTROL_BAR_HEIGHT
        return MIN_WINDOW_SIZE
