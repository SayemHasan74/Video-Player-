# LOCKED BEHAVIOR — see Section 2.5. Do not move rendering back onto the GUI thread, and do not simplify the WM_NCHITTEST border logic, without flagging it first.
"""Root application window and component controller."""

from __future__ import annotations

import logging
import ctypes
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QTimer, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QCursor, QDragEnterEvent, QDropEvent, QIcon, QKeyEvent, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QMenu, QMenuBar, QWidget

from config.settings import APP_NAME, CONTROL_BAR_HEIGHT, DEFAULT_WINDOW_SIZE, MIN_WINDOW_SIZE, SettingsStore, TITLE_BAR_HEIGHT, global_stylesheet
from core.history_manager import HistoryManager
from core.preferences import (
    DONT_HIDE_CURSOR_FULLSCREEN_WHILE_OSC_VISIBLE,
    ENABLE_TITLE_BAR_AND_OSC,
    HIDE_OSC_WHEN_CURSOR_OUTSIDE,
    OSC_HIDE_DELAY_MS,
    OSC_POSITION,
)
from core.filter_store import FilterStore
from core.keybindings import KeyBindingStore
from core.player_session import PlayerSession
from core.playlist_manager import PlaylistItem
from ui.osc import ControlBar, OscController
from ui.overlay_controller import OverlayController  # Compatibility name for architecture checks.
from ui.action_registry import ActionRegistry
from ui.crop_overlay import CropSelectionOverlay
from ui.input_controller import PlayerInputController
from ui.media_open_controller import MediaOpenController
from ui.media_state_controller import MediaStateController
from ui.music_mode import MusicModeController
from ui.native_overlay_stack import NativeOverlayStack
from ui.auxiliary_windows import HistoryWindow, InspectorWindow, PreferencesWindow, WelcomeWindow
from ui.filter_window import FiltersWindow
from ui.osd import OSDLabel
from ui.buffering_indicator import BufferingIndicator
from ui.osc_toolbar_editor import OscToolbarEditor
from ui.playback_event_router import PlaybackEventRouter
from ui.playlist_panel import PlaylistPanel
from ui.pip_window import PipWindow
from ui.plugin_ui_controller import PluginUiController
from ui.sidebar_controller import SidebarController
from ui.subtitle_finder_dialog import SubtitleFinderDialog
from ui.title_bar import TitleBar
from ui.track_menu import TrackMenuFactory
from ui.video_widget import VideoWidget
from ui.window_mode import WindowMode, WindowModeController
from utils.file_utils import is_probable_url
from utils.accessibility import transitions_enabled
from core.media_probe import matching_subtitles, probe_media
from ui.geometry import (
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTCAPTION,
    HTCLIENT,
    HTCLOSE,
    HTLEFT,
    HTMAXBUTTON,
    HTMINBUTTON,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    RECT as NativeRect,
    WM_DWMCOMPOSITIONCHANGED,
    WM_NCCALCSIZE,
    WM_NCHITTEST,
    WM_SIZING,
    correct_sizing_rect,
    dpi_aware_resize_hit_test,
    enable_dwm_custom_frame,
    native_message,
    point_from_lparam,
    video_aspect_from_probe,
)
from core.mpv_properties import (
    AF,
    HTTP_PROXY,
    SUB_BORDER_SIZE,
    SUB_CODEPAGE,
    SUB_COLOR,
    SUB_FONT,
    SUB_FONT_SIZE,
    SUB_POS,
    SUB_VISIBILITY,
    USER_AGENT,
    VF,
    VIDEO_ASPECT_OVERRIDE,
)
from core.video_pipeline import VideoPipelineConfig
from integrations.windows_media import WindowsMediaController
from utils.time_utils import format_time
from utils.thumbnail import ThumbnailWorker, trim_thumbnail_cache

from ui.osc_layout_constants import APP_MENU_HEIGHT, QUICK_SETTINGS_PANEL_WIDTH
class MainWindow(QMainWindow):
    """Frameless Comet Player main window."""

    def __init__(
        self,
        settings: SettingsStore,
        history: HistoryManager,
        startup_files: list[Path] | None = None,
        startup_url: str = "",
        window_manager: object | None = None,
        force_startup_current: bool = False,
        startup_scan_siblings: bool = True,
        initial_aspect: float = 0.0,
        initial_source: str = "",
        defer_startup_open: bool = False,
    ) -> None:
        super().__init__()
        self._native_frame_ready = False
        self._applying_dwm_frame = False
        self.settings = settings
        self.window_manager = window_manager
        self._startup_color_space = str(settings.get("video.color_space", "srgb"))
        self.history = history
        self._initial_aspect = max(0.0, float(initial_aspect))
        self._initial_source = str(initial_source)
        self.logger = logging.getLogger(__name__)
        self.key_store=KeyBindingStore(); self.filter_store=FilterStore(); self._binding_shortcuts:list[QShortcut]=[]; self._filter_shortcuts:list[QShortcut]=[]; self._menu_actions:dict[str,QAction]={}; self._key_profile_actions:dict[str,QAction]={}; self._key_profile_menu:QMenu|None=None; self._plugin_menu:QMenu|None=None
        self.video = VideoWidget(self)
        self.crop_overlay = CropSelectionOverlay(self.video)
        self.title_bar = TitleBar(self)
        self.control_bar = ControlBar(self)
        self.playlist_panel = PlaylistPanel(self)
        self.osd = OSDLabel(self.video, settings)
        self.drop_overlay = QLabel("Drop to play", self.video)
        self.buffering_indicator = BufferingIndicator(settings, self.video)
        self.thumbnail_preview = QLabel(self.video); self.thumbnail_preview.setStyleSheet("background:#080808;border:1px solid #444;padding:3px;"); self.thumbnail_preview.hide()
        self.track_menus = TrackMenuFactory(self)
        self.welcome_window: WelcomeWindow | None = None
        self.history_window: HistoryWindow | None = None
        self.filters_window: FiltersWindow | None = None
        self.inspector_window: InspectorWindow | None = None
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
        self._fullscreen_animation: QPropertyAnimation | None = None
        self._last_media_info: dict[str, object] = {}
        self._last_playlist_count = 0
        self._auto_resized_source = ""
        self._chrome_visible = True
        self._is_playing = False
        self._fullscreen_cursor_active = False
        self._fullscreen_cursor_timer = QTimer(self)
        self._fullscreen_cursor_timer.setSingleShot(True)
        self._fullscreen_cursor_timer.timeout.connect(self._hide_fullscreen_cursor)
        self.overlays = OscController(self)
        self.window_modes = WindowModeController(self)
        self.inputs = PlayerInputController(self)
        self.central_shell: QWidget | None = None
        self.app_menu_bar: QMenuBar | None = None
        self._thumbnail_worker: ThumbnailWorker | None = None
        self._thumbnails: dict[float,str] = {}
        self._thumbnail_signature: tuple[str,int] | None = None
        self._resize_layout_timer = QTimer(self)
        self._resize_layout_timer.setSingleShot(True)
        self._resize_layout_timer.setInterval(16)
        self._resize_layout_timer.timeout.connect(self._finish_resize_layout)
        self._pending_resize_geometry: QRect | None = None
        self._interactive_resize_timer = QTimer(self)
        self._interactive_resize_timer.setSingleShot(True)
        self._interactive_resize_timer.setInterval(16)
        self._interactive_resize_timer.timeout.connect(self._apply_pending_resize)
        self._build_window()
        self._dwm_frame_enabled = False
        self.native_overlays = NativeOverlayStack(self)
        self.native_overlays.register_many(
            (
                self.title_bar,
                self.crop_overlay,
                self.drop_overlay,
                self.buffering_indicator,
                self.thumbnail_preview,
                self.osd,
                self.playlist_panel,
                self.control_bar,
            )
        )
        self.sidebars = SidebarController(self)
        self.osd.configure()
        self.session = PlayerSession(self.video, settings, history, self)
        self.player = self.session.player
        self.pip_window = PipWindow(settings)
        self.playlist = self.session.playlist
        self.playlist.set_repeat_one(bool(self.settings.get("playlist.repeat_one", False)))
        self.playlist.set_repeat_all(bool(self.settings.get("playlist.repeat_all", False)))
        self.playlist.set_shuffle(bool(self.settings.get("playlist.shuffle", False)))
        self.media_states = self.session.media_states
        self.media_open = MediaOpenController(self)
        self.media_state = MediaStateController(self)
        self.plugin_ui = PluginUiController(self)
        self.plugins = self.plugin_ui.manager
        self.playback_events = PlaybackEventRouter(self)
        self.music_mode = MusicModeController(self)
        self.native_overlays.register(self.music_mode.view)
        self.media_controls = WindowsMediaController(
            bool(self.settings.get("audio.media_keys", True)), self
        )
        self._apply_player_preferences()
        for preset in self.filter_store.load():
            if preset.get("enabled"):
                self.player.add_filter(preset["kind"], preset["value"])
        self.actions = ActionRegistry(self)
        self._register_actions()
        self.media_controls.actionRequested.connect(self._handle_system_media_action)
        self._build_app_menu()
        self.native_overlays.register(self.app_menu_bar)
        self.native_overlays.watch_surface(self.video.render_window)
        self._load_keybindings()
        self._position_overlays()
        self._connect_signals()
        self.plugin_ui.load_enabled()
        self._restore_geometry()
        self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)), announce=False)
        self._apply_ui_preferences()
        self._native_frame_ready = True
        if defer_startup_open:
            pass
        elif startup_url:
            self.open_url(startup_url, apply_behavior=not force_startup_current)
        elif startup_files:
            self.open_files(
                startup_files,
                append=False if force_startup_current else None,
                scan_siblings=startup_scan_siblings,
            )
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

    @property
    def _current_position(self) -> float:
        return self.session.position

    @_current_position.setter
    def _current_position(self, value: float) -> None:
        self.session.position = float(value)

    @property
    def _current_duration(self) -> float:
        return self.session.duration

    @_current_duration.setter
    def _current_duration(self, value: float) -> None:
        self.session.duration = float(value)

    @property
    def _loaded_playlist_item(self) -> PlaylistItem | None:
        return self.session.loaded_item

    @_loaded_playlist_item.setter
    def _loaded_playlist_item(self, item: PlaylistItem | None) -> None:
        self.session.loaded_item = item

    def open_files(
        self,
        files: list[Path],
        append: bool | None = None,
        modifiers: object | None = None,
        scan_siblings: bool = True,
    ) -> None:
        self.media_open.open_files(files, append, modifiers, scan_siblings)

    def open_url(self, url: str, apply_behavior: bool = True, modifiers: object | None = None) -> None:
        self.media_open.open_url(url, apply_behavior, modifiers)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._resize_layout_timer.start()
        self.title_bar.set_maximized(self.isMaximized())

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        # Qt may recreate the HWND after a window-flag/state change. Reapply
        # the custom DWM frame to the current handle before it is interacted with.
        self._applying_dwm_frame = True
        try:
            self._dwm_frame_enabled = enable_dwm_custom_frame(int(self.winId()))
        finally:
            self._applying_dwm_frame = False

    def nativeEvent(self, event_type: object, message: object) -> tuple[bool, int]:
        """Own the Windows custom frame, hit testing, and live aspect lock."""
        if os.name != "nt":
            return super().nativeEvent(event_type, message)
        if not getattr(self, "_native_frame_ready", False) or getattr(
            self, "_applying_dwm_frame", False
        ):
            return False, 0
        try:
            msg = native_message(message)
        except (TypeError, ValueError, OSError):
            return False, 0

        if msg.message == WM_DWMCOMPOSITIONCHANGED:
            self._dwm_frame_enabled = enable_dwm_custom_frame(int(self.winId()))
            return False, 0
        if msg.message == WM_NCCALCSIZE:
            return True, 0
        if msg.message == WM_NCHITTEST:
            screen_x, screen_y = point_from_lparam(int(msg.lParam))
            if self.isFullScreen():
                return True, HTCLIENT
            border_hit = dpi_aware_resize_hit_test(int(self.winId()), screen_x, screen_y)
            if border_hit is not None:
                return True, border_hit
            global_point = QPoint(screen_x, screen_y)
            title_point = self.title_bar.mapFromGlobal(global_point)
            if self.title_bar.rect().contains(title_point):
                if self.title_bar.max_button.geometry().contains(title_point):
                    return True, HTMAXBUTTON
                if self.title_bar.min_button.geometry().contains(title_point):
                    return True, HTMINBUTTON
                if self.title_bar.close_button.geometry().contains(title_point):
                    return True, HTCLOSE
                return True, HTCAPTION
        if (
            msg.message == WM_SIZING
            and bool(self.settings.get("video.lock_resize_aspect", True))
            and not self._mini_mode
        ):
            aspect = self._media_aspect(self._last_media_info) or self._initial_aspect
            if aspect > 0:
                rect = ctypes.cast(int(msg.lParam), ctypes.POINTER(NativeRect)).contents
                extra_width, extra_height = self._video_layout_extras()
                minimum_width, minimum_height = self._resize_minimum_size()
                correct_sizing_rect(
                    rect,
                    int(msg.wParam),
                    aspect,
                    extra_width,
                    extra_height,
                    minimum_width,
                    minimum_height,
                )
                return True, 1
        return False, 0

    def _finish_resize_layout(self) -> None:
        self._position_overlays()
        if hasattr(self, "plugins"):
            self.plugins.events.emit("window.resized", {"width": self.width(), "height": self.height()})

    def moveEvent(self, event: object) -> None:
        super().moveEvent(event)
        self._position_overlays()

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        if self.settings.get(HIDE_OSC_WHEN_CURSOR_OUTSIDE, True):
            QTimer.singleShot(0, self._hide_chrome_if_cursor_outside)

    def _hide_chrome_if_cursor_outside(self) -> None:
        if (
            self.settings.get(HIDE_OSC_WHEN_CURSOR_OUTSIDE, True)
            and not self.frameGeometry().contains(QCursor.pos())
            and not self._mini_mode
            and not self._pip_mode
        ):
            self.overlays.animate(False)

    def changeEvent(self, event: object) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange or not hasattr(self, "music_mode"):
            return
        if self.isMinimized():
            if hasattr(self, "plugins"):
                self.plugins.events.emit("window.minimized")
            if bool(self.settings.get("window.minimize_to_pip_video", False)):
                QTimer.singleShot(0, self._enter_pip_after_minimize)
            if self.app_menu_bar is not None: self.app_menu_bar.hide()
            self.title_bar.hide()
            self.control_bar.hide()
        else:
            if hasattr(self, "plugins"):
                self.plugins.events.emit("window.restored")
            self.window_modes.sync_from_window()
            self._apply_mode_layout()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        current = self.playlist.current_item()
        self.settings.set("startup.last_source", current.source if current is not None else "")
        self.settings.set("playback.volume", self.control_bar.volume.slider.value())
        self.settings.save()
        self.playback_events.shutdown()
        self.media_controls.shutdown()
        self.music_mode.shutdown()
        self.plugin_ui.shutdown()
        self.media_open.shutdown()
        self.sidebars.stop()
        self.playlist_panel.shutdown()
        if self.pip_window.video_widget is self.video:
            self.pip_window.detach_video(self.central_shell)
        self.pip_window.shutdown(self)
        if self._thumbnail_worker and self._thumbnail_worker.isRunning():
            self._thumbnail_worker.cancel(); self._thumbnail_worker.wait(2000)
        self.title_bar.close()
        self.control_bar.close()
        self.session.shutdown()
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
        self.media_open.handle_drop(event)

    def mouseMoveEvent(self, event: object) -> None:
        if os.name == "nt":
            super().mouseMoveEvent(event)
            return
        if self._resize_edge:
            self._perform_resize(event.globalPosition().toPoint())
            return
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: object) -> None:
        if os.name == "nt":
            super().mousePressEvent(event)
            return
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
        if os.name == "nt":
            super().mouseReleaseEvent(event)
            return
        self._apply_pending_resize()
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
        # Chrome is an overlay. The native video surface always owns the full
        # client area; title/menu/OSC must never reserve a black gutter.
        self.setContentsMargins(0, 0, 0, 0)
        central = QWidget(self)
        self.central_shell = central
        central.setStyleSheet("background: #0d0d0d;")
        self.setCentralWidget(central)
        self.video.setParent(central)
        self.title_bar.setParent(self)
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
        self.title_bar.dragStarted.connect(self._start_system_move)
        self.video.doubleClicked.connect(self._toggle_fullscreen)
        self.video.clicked.connect(self._video_clicked)
        self.video.rightClicked.connect(self._show_context_menu)
        self.video.middleClicked.connect(self._toggle_mini_mode)
        self.video.scrolled.connect(self._handle_video_scroll)
        self.video.mouseMoved.connect(self._show_controls)
        self.video.mousePositionChanged.connect(self._handle_video_mouse_position)
        self.video.dragStarted.connect(self._start_video_window_drag)
        self.video.dragMoved.connect(self._move_video_window_drag)
        self.video.dragEnded.connect(self._end_video_window_drag)
        self.video.keyPressed.connect(self._handle_key)
        self.pip_window.restoreRequested.connect(self._toggle_pip)
        self.pip_window.playPauseRequested.connect(lambda: self.actions.trigger("play_pause"))
        self.pip_window.closePlayerRequested.connect(self.close)
        self.control_bar.playPauseClicked.connect(lambda: self.actions.trigger("play_pause"))
        self.control_bar.stopClicked.connect(lambda: self.actions.trigger("stop"))
        self.control_bar.nextClicked.connect(lambda: self.actions.trigger("next"))
        self.control_bar.previousClicked.connect(lambda: self.actions.trigger("previous"))
        self.control_bar.seekbar.hoverRequested.connect(self._show_thumbnail_preview)
        self.control_bar.seekbar.hoverEnded.connect(self.thumbnail_preview.hide)
        self.control_bar.muteClicked.connect(lambda: self.actions.trigger("mute"))
        self.control_bar.volumeWheel.connect(lambda delta: self.actions.trigger("change_volume", delta))
        self.control_bar.abLoopClicked.connect(lambda: self.actions.trigger("ab_loop"))
        self.control_bar.screenshotClicked.connect(lambda: self.actions.trigger("screenshot"))
        self.control_bar.subtitleClicked.connect(lambda: self.actions.trigger("subtitle_tracks"))
        self.control_bar.audioClicked.connect(lambda: self.actions.trigger("audio_tracks"))
        self.control_bar.playlistClicked.connect(lambda: self.actions.trigger("playlist"))
        self.control_bar.pipClicked.connect(lambda: self.actions.trigger("pip"))
        self.control_bar.musicClicked.connect(lambda: self.actions.trigger("music_mode"))
        self.control_bar.coverClicked.connect(lambda: self.actions.trigger("cover"))
        self.control_bar.fullscreenClicked.connect(lambda: self.actions.trigger("fullscreen"))
        self.control_bar.customizeRequested.connect(lambda: self.actions.trigger("customize_osc"))
        self.control_bar.floatingDragged.connect(self.overlays.move_floating)
        self.playlist.currentItemChanged.connect(self._load_playlist_item)
        self.playlist.playlistChanged.connect(self._playlist_changed)
        self.playlist_panel.itemActivated.connect(self.playlist.set_current)
        self.playlist_panel.removeRequested.connect(self.playlist.remove)
        self.playlist_panel.removeManyRequested.connect(self.playlist.remove_many)
        self.playlist_panel.addRequested.connect(self.media_open.choose_files)
        self.playlist_panel.chapterActivated.connect(lambda position: self.actions.trigger("seek_absolute", position))
        self.playlist_panel.quickSettingChanged.connect(self.media_state.apply_quick_setting)
        self.playlist_panel.quick_settings.findSubtitles.connect(self._show_subtitle_finder)
        self.playlist_panel.quick_settings.cropSelectionRequested.connect(self.crop_overlay.begin)
        self.crop_overlay.selectionFinished.connect(self.media_state.crop_selection_finished)
        self.playlist_panel.moveRequested.connect(self.playlist.move)
        self.playlist_panel.moveManyRequested.connect(self.playlist.move_many)
        self.playlist_panel.sortRequested.connect(self.playlist.sort_items)
        self.playlist_panel.playNextRequested.connect(self._queue_playlist_item_next)
        self.playlist_panel.tabChanged.connect(lambda name: self.settings.set("ui.sidebar_tab", name))
        self.playlist_panel.keyPressed.connect(self._handle_key)
        self.playlist_panel.metadataChanged.connect(self.music_mode.metadata_ready)
        self.playlist_panel.newWindowRequested.connect(self.media_open.open_source_in_new_window)
        self.playlist_panel.addSubtitleRequested.connect(self._add_playlist_subtitle)
        self.playlist_panel.subtitleViewRequested.connect(self._view_playlist_subtitle)
        self.playlist_panel.subtitleWrongRequested.connect(self._mark_playlist_subtitle_wrong)
        self.playlist_panel.repeatOneToggled.connect(self._set_repeat_one)
        self.playlist_panel.repeatAllToggled.connect(self._set_repeat_all)
        self.playlist_panel.shuffleToggled.connect(self._set_shuffle)
        self.playlist_panel.set_playback_modes(self.playlist.repeat_one, self.playlist.repeat_all, self.playlist.shuffle)
        self.window_modes.modeChanged.connect(self._window_mode_changed)
        self.playback_events.connect_all()
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
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self, activated=self.media_open.paste_playlist_content)
        paste_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        QTimer.singleShot(0, lambda: self.plugins.events.emit("window.loaded"))

    def _register_actions(self) -> None:
        """Register each player command once for every UI entry point."""
        actions = {
            "open_file": ("Open File…", self.media_open.choose_files),
            "open_folder": ("Open Folder…", self.media_open.choose_folder),
            "open_url": ("Open URL…", lambda: self.media_open.show_url_dialog("")),
            "history": ("History", self._show_history),
            "screenshot": ("Screenshot", self._save_screenshot),
            "quit": ("Quit", self.close),
            "play": ("Play", lambda: self.player.set_paused(False)),
            "pause": ("Pause", lambda: self.player.set_paused(True)),
            "play_pause": ("Play/Pause", self.player.play_pause),
            "stop": ("Stop", self.player.stop),
            "previous": ("Previous", self._play_previous),
            "next": ("Next", self._play_next),
            "seek_backward": ("Seek Backward", lambda: self.player.seek_relative(-5)),
            "seek_forward": ("Seek Forward", lambda: self.player.seek_relative(5)),
            "seek_absolute": ("Seek", self.player.seek_absolute),
            "seek_ui": ("Seek from OSC", self.player.complete_ui_seek),
            "volume_up": ("Volume Up", lambda: self.player.change_volume(5)),
            "volume_down": ("Volume Down", lambda: self.player.change_volume(-5)),
            "change_volume": ("Change Volume", self.player.change_volume),
            "set_volume": ("Set Volume", self.player.set_volume),
            "set_speed": ("Set Speed", self.player.set_speed),
            "ab_loop": ("A–B Loop", self._cycle_ab_loop),
            "fullscreen": ("Fullscreen", self._toggle_fullscreen),
            "exit_fullscreen": ("Exit Fullscreen", self.window_modes.exit_fullscreen),
            "show_osc": ("Show OSC Momentarily", self._show_osc_momentarily),
            "cover": ("Fit/Cover", self._toggle_cover_mode),
            "crop_select": ("Select Crop…", self.crop_overlay.begin),
            "filters": ("Filters", self._show_filters),
            "inspector": ("Inspector", self._show_inspector),
            "audio_tracks": ("Audio Tracks", self._show_audio_menu),
            "mute": ("Mute", self.player.toggle_mute),
            "subtitle_tracks": ("Subtitle Tracks", self._show_subtitle_menu),
            "subtitle_visibility": ("Hide/Show All", self._toggle_subtitle_visibility),
            "find_subtitles": ("Find Online…", self._show_subtitle_finder),
            "playlist": ("Playlist", self._toggle_playlist),
            "pin_playlist": ("Pin Playlist Sidebar", self._toggle_playlist_pin),
            "pin_quick_settings": ("Pin Quick Settings Opposite", self._toggle_quick_settings_pin),
            "music_mode": ("Music Mode", self._toggle_mini_mode),
            "pip": ("Picture in Picture", self._toggle_pip),
            "customize_osc": ("Customize OSC Toolbar…", self._show_osc_toolbar_editor),
            "always_on_top": ("Always on Top", self._toggle_always_on_top),
            "preferences": ("Preferences", self._show_settings),
            "manage_plugins": ("Manage Plugins…", self.plugin_ui.show_manager),
            "reload_plugins": ("Reload Plugins", self.plugins.reload_all),
            "plugin_folder": ("Open Plugins Folder", self.plugin_ui.open_folder),
            "about": ("About Comet V2", lambda: self.osd.show_message("Comet V2 • IINA-inspired media player")),
        }
        for action_id, (label, callback) in actions.items():
            self.actions.register(action_id, label, callback)

    def trigger_action(self, action_id: str) -> None:
        self.actions.trigger(action_id)

    def _build_app_menu(self) -> None:
        bar = QMenuBar(self)
        self.app_menu_bar = bar
        bar.setNativeMenuBar(False)
        bar.setStyleSheet("QMenuBar { background: #0d0d0d; color: #eeeeee; padding-left: 6px; } QMenuBar::item { padding: 7px 10px; background: transparent; } QMenuBar::item:selected { background: #242424; }")
        menus = {
            "File": ("open_file", "open_folder", "open_url", "history", "screenshot", "quit"),
            "Playback": ("play_pause", "stop", "previous", "next", "ab_loop"),
            "Video": ("fullscreen", "cover", "crop_select", "filters", "inspector"),
            "Audio": ("audio_tracks", "mute"),
            "Subtitle": ("subtitle_tracks", "subtitle_visibility", "find_subtitles"),
            "Window": ("playlist", "pin_playlist", "pin_quick_settings", "music_mode", "pip", "customize_osc", "always_on_top", "preferences"),
            "Plugins": ("manage_plugins", "reload_plugins", "plugin_folder"),
            "Help": ("about",),
        }
        for title, entries in menus.items():
            menu = bar.addMenu(title)
            if title == "Plugins":
                self._plugin_menu = menu
            for action_id in entries:
                action = self.actions.qaction(action_id, self)
                menu.addAction(action)
                self._menu_actions[action_id] = action
            if title == "Window":
                self._key_profile_menu = menu.addMenu("Key Binding Profile")
                self._refresh_key_profile_menu()
        bar.raise_()

    def _action_callbacks(self) -> dict[str, object]:
        return self.actions.callbacks()

    def _handle_system_media_action(self, action: str) -> None:
        self.actions.trigger(str(action))

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
        self._binding_shortcuts=[]; bindings=self.key_store.load(str(self.settings.get("keys.profile","Default"))); callbacks=self._action_callbacks()
        for action in self._menu_actions.values():
            action.setShortcut(QKeySequence())
        for key,action_id in bindings.items():
            callback=callbacks.get(action_id)
            if callback:
                if QKeySequence(key).matches(QKeySequence(Qt.Key.Key_Space)) == QKeySequence.SequenceMatch.ExactMatch:
                    continue
                menu_action = self._menu_actions.get(action_id)
                if menu_action is not None:
                    # A QAction and QShortcut with the same key become
                    # ambiguous and neither fires. Menu-backed commands use
                    # the QAction as their sole application-wide shortcut.
                    menu_action.setShortcut(QKeySequence(key))
                    menu_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
                    continue
                shortcut=QShortcut(QKeySequence(key),self,activated=callback);shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut);self._binding_shortcuts.append(shortcut)
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
        self.osd.show_message(f"{preset['name']}: {'On' if preset['enabled'] else 'Off'}", category="filters")

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if self._handle_window_edge_event(watched, event):
            return True
        if (
            self.isFullScreen()
            and event.type() == QEvent.Type.MouseMove
            and isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
        ):
            # The native render QWindow has its own direct signal path. This
            # covers every QWidget region above it (OSD, menus, sidebars, and
            # transient overlays) so fullscreen activity cannot be lost when
            # the pointer is not currently over the render child.
            self._show_controls()
        if watched is self.title_bar or watched is self.control_bar:
            if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._show_player_chrome()
                if self._is_playing:
                    self._schedule_hide_player_chrome(3000)
            elif event.type() == QEvent.Type.Leave and self._is_playing:
                self._schedule_hide_player_chrome(3000)
        return super().eventFilter(watched, event)

    def _load_playlist_item(self, item: PlaylistItem) -> None:
        gapless_transition = self.player.consume_gapless_transition(item.source)
        resume = self.session.begin_item(item)
        if not item.is_url and not Path(item.source).exists():
            self.osd.show_message(f"File not found: {item.title}", "warning", category="playlist")
            self._play_next()
            return
        initial_geometry_is_ready = item.source == self._auto_resized_source
        if not initial_geometry_is_ready:
            self._auto_resized_source = ""
        if not item.is_url and not initial_geometry_is_ready:
            self._prepare_geometry_for_source(item.source)
        self.title_bar.set_title(item.title)
        self._cover_mode = False
        self.control_bar.set_cover_mode(False)
        self.settings.set("playback.cover_mode", False)
        if not gapless_transition:
            self.player.load(item.source, resume)
        self.plugins.events.emit("file.started", {"source": item.source, "title": item.title})
        QTimer.singleShot(50, lambda source=item.source: self.media_state.apply_for_source(source))
        QTimer.singleShot(0, lambda source=item.source: self.plugins.events.emit("file.loaded", {"source": source}))
        subtitle_candidates = list(item.subtitle_paths)
        if not item.is_url and item.autoload_subtitles and self.settings.get("subtitle.autoload", True):
            subtitle_candidates.extend(matching_subtitles(item.source))
        seen_subtitles: set[str] = set()
        subtitle_candidates = [
            subtitle for subtitle in subtitle_candidates
            if not (
                (key := str(Path(subtitle).resolve()).casefold()) in item.wrong_subtitles
                or key in seen_subtitles
                or seen_subtitles.add(key)
            )
        ]
        if not item.is_url:
            for index, subtitle in enumerate(subtitle_candidates):
                self.player.load_subtitle(Path(subtitle), select=index == 0, secondary=index == 1)
        self.player.set_cover_mode(False)
        self.osd.show_message("Playing", category="playback")
        QTimer.singleShot(0, self._queue_gapless_successor)

    def _queue_gapless_successor(self) -> None:
        current = self.playlist.current_item()
        successor = self.playlist.peek_next()
        if current is None or successor is None or successor.is_url:
            return
        if not (
            self.music_mode.is_audio_extension(current.source)
            and self.music_mode.is_audio_extension(successor.source)
        ):
            return
        self.player.queue_gapless(successor.source)

    def _gapless_advanced(self, source: str) -> None:
        successor = self.playlist.peek_next()
        if successor is not None and self.player.sources_equal(successor.source, source):
            self.playlist.next()

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
        pixmap=pixmap.scaledToWidth(240,Qt.TransformationMode.SmoothTransformation); self.thumbnail_preview.setPixmap(pixmap); self.thumbnail_preview.adjustSize(); global_point=self.control_bar.seekbar.mapToGlobal(point); local=self.video.mapFromGlobal(global_point); x=max(0,min(self.video.width()-self.thumbnail_preview.width(),local.x()-self.thumbnail_preview.width()//2)); y=max(0,self.video.height()-self.control_bar.height()-self.thumbnail_preview.height()-12); self.thumbnail_preview.move(x,y); self.thumbnail_preview.show(); self.thumbnail_preview.raise_()

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

    def _set_repeat_one(self, enabled: bool) -> None:
        self.playlist.set_repeat_one(enabled)
        self.settings.set("playlist.repeat_one", bool(enabled))
        self.settings.save()

    def _set_repeat_all(self, enabled: bool) -> None:
        self.playlist.set_repeat_all(enabled)
        self.settings.set("playlist.repeat_all", bool(enabled))
        self.settings.save()

    def _set_shuffle(self, enabled: bool) -> None:
        self.playlist.set_shuffle(enabled)
        self.settings.set("playlist.shuffle", bool(enabled))
        self.settings.save()

    def _playlist_item_for_source(self, source: str) -> PlaylistItem | None:
        return next((item for item in self.playlist.items if item.source == source), None)

    def _playlist_changed(self) -> None:
        previous = self._last_playlist_count
        current = len(self.playlist.items)
        self._last_playlist_count = current
        self._refresh_playlist()
        if current > previous:
            text = f"Added {current - previous} item{'s' if current - previous != 1 else ''} to playlist"
        elif current < previous:
            text = f"Removed {previous - current} item{'s' if previous - current != 1 else ''} from playlist"
        else:
            text = "Playlist updated"
        self.osd.show_message(text, category="playlist")

    @staticmethod
    def _track_name(tracks: list[dict], track_id: object) -> str:
        if str(track_id) == "no":
            return "Off"
        track = next((entry for entry in tracks if entry.get("id") == track_id), None)
        if track is None:
            return str(track_id)
        return str(track.get("title") or track.get("lang") or f"Track {track_id}")

    def _load_external_subtitle(self, subtitle: str, secondary: bool = False) -> object:
        path = Path(subtitle)
        track_id = self.player.load_subtitle(path, select=not secondary, secondary=secondary)
        if track_id not in (None, False, "no"):
            label = "Secondary subtitle" if secondary else "Subtitle"
            self.osd.show_message(f"{label} loaded: {path.name}", "success", category="subtitles")
        return track_id

    def _add_playlist_subtitle(self, source: str, subtitle: str) -> None:
        item = self._playlist_item_for_source(source)
        if item is None:
            return
        path = str(Path(subtitle).resolve())
        if path not in item.subtitle_paths:
            item.subtitle_paths.append(path)
        item.wrong_subtitles.discard(path.casefold())
        item.has_subtitle = True
        if self.playlist.current_item() is item:
            self._load_external_subtitle(path)
        self._refresh_playlist()

    def _view_playlist_subtitle(self, source: str, subtitle: str) -> None:
        item = self._playlist_item_for_source(source)
        if item is self.playlist.current_item():
            self._load_external_subtitle(subtitle)
        else:
            self.osd.show_message("Play this item before viewing its subtitle", "warning", category="subtitles")

    def _mark_playlist_subtitle_wrong(self, source: str, subtitle: str) -> None:
        item = self._playlist_item_for_source(source)
        if item is None:
            return
        key = str(Path(subtitle).resolve()).casefold()
        item.wrong_subtitles.add(key)
        item.subtitle_paths = [path for path in item.subtitle_paths if str(Path(path).resolve()).casefold() != key]
        remaining = [] if not item.autoload_subtitles else [
            path for path in matching_subtitles(item.source)
            if str(Path(path).resolve()).casefold() not in item.wrong_subtitles
        ]
        item.has_subtitle = bool(remaining or item.subtitle_paths)
        self._refresh_playlist()

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
                if action is None:
                    continue
                if action_id == "playlist":
                    # Use a menu-owned proxy and defer opening until QMenu has
                    # released its mouse grab. Otherwise the application-wide
                    # outside-click filter can hide the panel on the same click.
                    playlist_action = menu.addAction(action.icon(), action.text())
                    playlist_action.triggered.connect(
                        lambda: QTimer.singleShot(0, lambda: self.actions.trigger("playlist"))
                    )
                else:
                    menu.addAction(action)
        contributions = self.plugins.menu_items("context")
        if contributions:
            menu.addSeparator()
            for item in contributions:
                action = menu.addAction(item.title)
                action.triggered.connect(lambda _checked=False, contribution=item: self.plugins.invoke(contribution))
        menu.exec(position)

    def _show_playlist_from_context(self) -> None:
        if self._mini_mode:
            return
        self._set_playlist_visible(True)
        self._show_controls()

    def _toggle_subtitle_visibility(self) -> None:
        visible = bool(self.player.get_property(SUB_VISIBILITY, True))
        self.player.set_property(SUB_VISIBILITY, not visible)
        self.osd.show_message(f"Subtitles: {'On' if not visible else 'Hidden'}", category="tracks")

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
                self._load_external_subtitle(path)
        elif data == "__find_online__":
            self._show_subtitle_finder()
        elif data is not None:
            self.player.set_subtitle_track(data)
            self.osd.show_message(f"Subtitle track: {self._track_name(self.subtitle_tracks, data)}", category="tracks")

    def _show_subtitle_finder(self) -> None:
        current = self.playlist.current_item()
        source = current.source if current is not None else ""
        dialog = SubtitleFinderDialog(source, self)
        dialog.searchStarted.connect(
            lambda provider: self.osd.show_message(
                f"Searching subtitles with {provider}…", duration=0, category="subtitles"
            )
        )
        dialog.subtitleSelected.connect(self._load_external_subtitle)
        dialog.finished.connect(
            lambda _result: self.osd.dismiss("subtitles") if not self.osd.timer.isActive() else None
        )
        self.osd.show_message("Subtitle search ready", duration=0, category="subtitles")
        dialog.exec()

    def _show_audio_menu(self) -> None:
        menu = self.track_menus.audio_menu(self.audio_tracks)
        action = menu.exec(self.control_bar.audio_button.mapToGlobal(QPoint(0, 36)))
        if action is not None and action.data() is not None:
            self.player.set_audio_track(action.data())
            self.osd.show_message(f"Audio track: {self._track_name(self.audio_tracks, action.data())}", category="tracks")

    def _show_settings(self) -> None:
        dialog = PreferencesWindow(self.settings, self.history, self)
        if dialog.exec():
            self._apply_always_on_top(bool(self.settings.get("window.always_on_top", False)))
            self._apply_player_preferences()
            self._apply_ui_preferences()
            self.osd.configure()
            self.playlist_panel.set_side(str(self.settings.get("ui.sidebar_side", "right")))
            self.playlist_panel.set_current_tab(str(self.settings.get("ui.sidebar_tab", "playlist")))
            if not self.settings.get("ui.hide_controls_while_playing", True):
                self.overlays.hide_timer.stop(); self._show_player_chrome()
            self._load_keybindings()
            self._refresh_key_profile_menu()

    def _show_osc_toolbar_editor(self) -> None:
        current = self.settings.get("ui.osc_toolbar", [])
        dialog = OscToolbarEditor(
            [str(item) for item in current] if isinstance(current, list) else [], self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        order = self.control_bar.set_toolbar_order(dialog.selected_order())
        self.settings.set("ui.osc_toolbar", order)
        self.settings.save()
        self._position_overlays()

    def _apply_player_preferences(self) -> None:
        """Apply settings that mpv can change safely during the current session."""
        if hasattr(self, "media_controls"):
            self.media_controls.set_enabled(bool(self.settings.get("audio.media_keys", True)))
        self.player.set_volume(int(self.settings.get("playback.volume", 80)))
        self.player.set_muted(bool(self.settings.get("playback.muted", False)))
        self.player.set_speed(float(self.settings.get("playback.speed", 1.0)))
        self.player.set_loglevel(str(self.settings.get("advanced.mpv_loglevel", "warn")))
        pipeline = VideoPipelineConfig.from_settings(self.settings)
        if pipeline.color_space != self._startup_color_space:
            pipeline = replace(pipeline, color_space=self._startup_color_space)
        self.player.configure_video_pipeline(pipeline)
        self.player.configure_audio(
            replaygain=str(self.settings.get("audio.replaygain", "no")),
            replaygain_preamp=float(self.settings.get("audio.replaygain_preamp", 0.0)),
            replaygain_clip=bool(self.settings.get("audio.replaygain_clip", False)),
            replaygain_fallback=float(self.settings.get("audio.replaygain_fallback", 0.0)),
            gapless=self.settings.get("audio.gapless", "weak"),
            languages=self.settings.get("audio.languages", ""),
            device=str(self.settings.get("audio.device", "auto")),
        )
        self.player.configure_subtitles(
            exclude_embedded_auto=bool(self.settings.get("subtitle.exclude_embedded_auto", False))
        )
        properties = {
            VIDEO_ASPECT_OVERRIDE: "no" if self.settings.get("video.aspect", "auto") == "auto" else self.settings.get("video.aspect", "auto"),
            SUB_FONT: self.settings.get("subtitle.font", "Segoe UI"),
            SUB_FONT_SIZE: self.settings.get("subtitle.size", 42),
            SUB_COLOR: self.settings.get("subtitle.color", "#ffffff"),
            SUB_BORDER_SIZE: self.settings.get("subtitle.outline", 2),
            SUB_POS: self.settings.get("subtitle.position", 100),
            SUB_CODEPAGE: self.settings.get("subtitle.encoding", "auto"),
        }
        proxy = str(self.settings.get("network.proxy", "")).strip()
        user_agent = str(self.settings.get("network.user_agent", "")).strip()
        if proxy: properties[HTTP_PROXY] = proxy
        if user_agent: properties[USER_AGENT] = user_agent
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
        self.control_bar.set_layout_mode(str(self.settings.get(OSC_POSITION, "floating")))
        toolbar = self.settings.get("ui.osc_toolbar", [])
        self.control_bar.set_toolbar_order(toolbar if isinstance(toolbar, list) else [])
        self.control_bar.set_scroll_enabled(bool(self.settings.get("ui.osc_scroll_enabled", True)))
        self.osd.configure()
        self.buffering_indicator.apply_preferences()
        if not self.settings.get(ENABLE_TITLE_BAR_AND_OSC, True):
            self._chrome_visible = False
            self.overlays.hide_timer.stop()
        elif not self._chrome_visible and not self._is_playing:
            self._chrome_visible = True
        if self.settings.get("ui.osc_always_visible", False):
            self._chrome_visible = True
            self.overlays.hide_timer.stop()
        self._position_overlays()
        if hasattr(self, "sidebars"):
            self.sidebars.apply_preferences()
        if hasattr(self, "music_mode"):
            self.music_mode.apply_preferences()

    def _sidebar_width_changed(self, width: int) -> None:
        self.settings.set("ui.sidebar_width", int(width))
        self._position_overlays()

    def _show_welcome(self) -> None:
        if self.playlist.current_item() is not None:
            return
        self.welcome_window = WelcomeWindow(
            self.history,
            str(self.settings.get("startup.last_source", "")),
            self,
            settings=self.settings,
        )
        self.welcome_window.openFilesRequested.connect(
            lambda files, modifiers: (self.open_files(files, None, modifiers), self.welcome_window.close())
        )
        self.welcome_window.openUrlRequested.connect(
            lambda url, modifiers: self.open_url(url, modifiers=modifiers)
            if url else self.media_open.show_url_dialog()
        )
        self.welcome_window.show()

    def _show_history(self) -> None:
        self.history_window = HistoryWindow(self.history, self, settings=self.settings)
        self.history_window.openSourceRequested.connect(self._open_history_source)
        self.history_window.show()

    def _open_history_source(self, source: str, modifiers: object) -> None:
        if is_probable_url(source):
            self.open_url(source, modifiers=modifiers)
        else:
            self.open_files([Path(source)], None, modifiers)

    def _show_inspector(self) -> None:
        current = self.playlist.current_item()
        if current is None:
            return
        self.inspector_window = InspectorWindow(self.player, current.source, self)
        self.inspector_window.show()

    def _show_filters(self) -> None:
        self.filters_window = FiltersWindow(self, self.filter_store)
        self.filters_window.applyFilter.connect(self._apply_filter)
        self.filters_window.removeFilter.connect(self._remove_filter)
        self.player.filtersChanged.connect(self.filters_window.set_active_filters)
        self.filters_window.savedFiltersChanged.connect(self._load_filter_shortcuts)
        self.filters_window.set_active_filters(
            self.player.get_property(VF, []) or [],
            self.player.get_property(AF, []) or [],
        )
        self.filters_window.show()

    def _apply_filter(self, kind: str, value: str) -> None:
        self.player.add_filter(kind, value)
        self.osd.show_message(f"{kind.title()} filter added", category="filters")

    def _remove_filter(self, kind: str, value: str) -> None:
        self.player.remove_filter(kind, value)
        self.osd.show_message(f"{kind.title()} filter removed", category="filters")

    def _save_screenshot(self) -> None:
        directory = Path(str(self.settings.get("paths.screenshot_dir", Path.home() / "Desktop")))
        if not directory.exists() or not directory.is_dir():
            directory = Path.home() / "Desktop"
        filename = f"CometPlayer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output = directory / filename
        if self.player.screenshot(output):
            self.osd.show_message(f"Screenshot saved: {filename}", "success", category="screenshot")
        else:
            self.osd.show_message("Screenshot failed", "error", category="screenshot")

    def _cycle_ab_loop(self) -> None:
        if self._ab_a is None:
            self._ab_a = self._current_position
            self.control_bar.set_ab_state(f"A: {format_time(self._ab_a)} - Click to set B", True)
            self.osd.show_message(f"A-loop start: {format_time(self._ab_a)}", category="ab_loop")
        elif self._ab_b is None:
            self._ab_b = max(self._current_position, self._ab_a + 1)
            self.player.set_ab_loop(self._ab_a, self._ab_b)
            self.control_bar.set_ab_state(f"A-B: {format_time(self._ab_a)} - {format_time(self._ab_b)}", True)
            self.osd.show_message(
                f"A-B loop: {format_time(self._ab_a)} – {format_time(self._ab_b)}",
                category="ab_loop",
            )
        else:
            self._ab_a = None
            self._ab_b = None
            self.player.set_ab_loop(None, None)
            self.control_bar.set_ab_state("Set A-B loop", False)
            self.osd.show_message("A-B loop cleared", category="ab_loop")

    def _handle_video_scroll(self, delta: int) -> None:
        if not self.settings.get("ui.video_scroll_enabled", True):
            return
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

    def _animate_fullscreen_change(self, change: object, finished: object) -> None:
        """Fade around the native fullscreen switch using the global animation preference."""
        if not transitions_enabled(self.settings) or not self.isVisible():
            change(); finished(); return
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(85)
        fade_out.setStartValue(max(0.0, self.windowOpacity()))
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fullscreen_animation = fade_out

        def switch_and_fade_in() -> None:
            change()
            self.setWindowOpacity(0.0)
            fade_in = QPropertyAnimation(self, b"windowOpacity", self)
            fade_in.setDuration(115)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InCubic)
            self._fullscreen_animation = fade_in
            def complete() -> None:
                self.setWindowOpacity(1.0)
                self._fullscreen_animation = None
                finished()
            fade_in.finished.connect(complete)
            fade_in.start()

        fade_out.finished.connect(switch_and_fade_in)
        fade_out.start()

    def _pause_and_minimize(self) -> None:
        self.player.set_paused(True)
        self.showMinimized()

    def _toggle_mini_mode(self) -> None:
        self.music_mode.toggle_manual()

    def _enter_mini_mode(self) -> None:
        self.session.music_mode_manual_override = True
        self.window_modes.enter_compact()

    def _exit_mini_mode(self) -> None:
        self.session.music_mode_manual_override = False
        self.window_modes.exit_compact()

    def _prepare_mode_transition(self) -> None:
        """Stop transient UI work before one atomic window-state transition."""
        self.overlays.stop_transients()
        self.sidebars.suspend()

    def _set_top_chrome_reserved(self, enabled: bool) -> None:
        """Compatibility hook: player chrome never reserves video geometry."""
        del enabled
        if self.contentsMargins().top() != 0:
            self.setContentsMargins(0, 0, 0, 0)

    def _apply_mode_layout(self) -> None:
        """Apply chrome visibility for the controller's current explicit mode."""
        if self._pip_mode:
            self._set_top_chrome_reserved(False)
            if self.app_menu_bar is not None:
                self.app_menu_bar.hide()
            self.title_bar.hide()
            self.control_bar.hide()
            self.sidebars.suspend()
            return
        if self._mini_mode:
            self._set_top_chrome_reserved(False)
            if self.app_menu_bar is not None:
                self.app_menu_bar.hide()
            self.title_bar.hide()
            self.control_bar.hide()
            self.music_mode.view.show()
            self.music_mode.view.raise_()
            self._position_overlays()
            return
        if hasattr(self, "music_mode"):
            self.music_mode.view.hide()
        visible = (
            self._chrome_visible
            and not self._pip_mode
            and bool(self.settings.get(ENABLE_TITLE_BAR_AND_OSC, True))
        )
        self._set_top_chrome_reserved(
            bool(self.settings.get(ENABLE_TITLE_BAR_AND_OSC, True))
        )
        if self.app_menu_bar is not None:
            self.app_menu_bar.setVisible(visible)
        self.title_bar.setVisible(visible)
        self.control_bar.setVisible(visible)
        self.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not visible)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not visible)
        self._position_overlays()
        if visible:
            self.overlays.raise_chrome()
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
        if self._pip_mode:
            self.window_modes.exit_pip()
        if self._mini_mode:
            self.music_mode.toggle_playlist()
            return
        self.sidebars.toggle_playlist()

    def _set_playlist_visible(self, visible: bool) -> None:
        """Show or hide the playlist and keep its persisted UI state in sync."""
        if self._mini_mode:
            self.music_mode.set_playlist_expanded(visible)
            return
        self.sidebars.set_playlist_visible(visible)

    def _toggle_playlist_pin(self) -> None:
        self.sidebars.set_playlist_pinned(not self.sidebars.playlist_pinned)

    def _toggle_quick_settings_pin(self) -> None:
        self.sidebars.set_quick_pinned(not self.sidebars.quick_pinned)

    def _is_playlist_widget(self, widget: QWidget | None) -> bool:
        """Return whether a clicked widget belongs to the playlist panel."""
        return self.sidebars.is_sidebar_widget(widget)

    def _is_playlist_toggle_widget(self, widget: QWidget | None) -> bool:
        return widget in {self.control_bar.playlist_button, self.music_mode.view.playlist_button}

    def _toggle_pip(self) -> None:
        if not self._pip_mode and not self._can_enter_pip():
            self.osd.show_message("Picture in Picture is available for video playback", "warning")
            return
        self.window_modes.toggle_pip()
        if not self._pip_mode:
            self.raise_()
            self.activateWindow()
        self.osd.show_message(f"Picture in Picture: {'On' if self._pip_mode else 'Off'}")

    def _can_enter_pip(self) -> bool:
        return (
            bool(self.player.is_loaded)
            and bool(self._last_media_info.get("has_video", False))
            and not self._mini_mode
        )

    def _enter_pip_after_minimize(self) -> None:
        if self._pip_mode or not self.isMinimized() or not self._can_enter_pip():
            return
        if self.window_modes.mode is WindowMode.FULLSCREEN:
            self.showFullScreen()
        elif self.window_modes.mode is WindowMode.MAXIMIZED:
            self.showMaximized()
        else:
            self.showNormal()
        self.window_modes.enter_pip()

    def _media_info_changed(self, info: dict[str, object]) -> None:
        self._last_media_info = dict(info)
        self.music_mode.media_info_changed(info)
        self.media_controls.update_metadata(info)
        self._auto_resize_for_media(info)

    def _window_mode_changed(self, mode: WindowMode) -> None:
        self.plugins.events.emit("window.mode", mode.name.lower())
        if mode is WindowMode.FULLSCREEN:
            self._reveal_fullscreen_cursor()
        else:
            self._update_cursor_visibility()

    def _video_clicked(self) -> None:
        if not self._pip_mode:
            self._animate_player_chrome(not self._chrome_visible)

    def _start_video_window_drag(self, global_pos: QPoint) -> None:
        if self._pip_mode:
            return
        if self.isMaximized() or self.isFullScreen() or self._mini_mode:
            return
        self._start_system_move(global_pos)

    def _move_video_window_drag(self, global_pos: QPoint) -> None:
        del global_pos

    def _end_video_window_drag(self) -> None:
        pass

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
        self.music_mode.sync_current_item()
        self.plugins.events.emit("playlist.changed", self.plugin_ui.plugin_playlist_items())

    def _show_controls(self) -> None:
        if self._pip_mode:
            return
        self._show_player_chrome()
        if self._is_playing and not self._mini_mode:
            self._schedule_hide_player_chrome(3000)
        self._reveal_fullscreen_cursor()
        self._update_cursor_visibility()

    def _show_osc_momentarily(self) -> None:
        self.overlays.show_momentarily()

    def _update_cursor_visibility(self) -> None:
        if not self.isFullScreen():
            self._fullscreen_cursor_timer.stop()
            self._fullscreen_cursor_active = False
            self._unset_player_cursor()
            return
        keep_visible = bool(
            self._chrome_visible
            and (
                self._fullscreen_cursor_active
                or self.settings.get(
                    DONT_HIDE_CURSOR_FULLSCREEN_WHILE_OSC_VISIBLE,
                    False,
                )
            )
        )
        self._set_player_cursor(
            Qt.CursorShape.ArrowCursor if keep_visible else Qt.CursorShape.BlankCursor
        )


    def _reveal_fullscreen_cursor(self) -> None:
        """Show the cursor on activity, then let the shared OSC timeout hide it."""
        if not self.isFullScreen():
            return
        self._fullscreen_cursor_active = True
        delay = max(100, int(self.settings.get(OSC_HIDE_DELAY_MS, 3000)))
        self._fullscreen_cursor_timer.start(delay)
        self._set_player_cursor(Qt.CursorShape.ArrowCursor)

    def _hide_fullscreen_cursor(self) -> None:
        self._fullscreen_cursor_active = False
        self._update_cursor_visibility()

    def _set_player_cursor(self, shape: Qt.CursorShape) -> None:
        """Apply cursor state to Qt widgets and the embedded native QWindow."""
        cursor = QCursor(shape)
        self.setCursor(cursor)
        self.video.setCursor(cursor)
        self.video.container.setCursor(cursor)
        render_window = self.video.render_window
        if hasattr(render_window, "setCursor"):
            render_window.setCursor(cursor)

    def _unset_player_cursor(self) -> None:
        self.unsetCursor()
        self.video.unsetCursor()
        self.video.container.unsetCursor()
        render_window = self.video.render_window
        if hasattr(render_window, "unsetCursor"):
            render_window.unsetCursor()

    def _note_user_activity(self) -> None:
        """Keep chrome predictable: every player input restarts one hide timer."""
        if self._pip_mode:
            return
        self._show_player_chrome()
        if self._is_playing and not self._mini_mode:
            self._schedule_hide_player_chrome(int(self.settings.get(OSC_HIDE_DELAY_MS, 3000)))

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
        if self._pip_mode:
            return
        self.overlays.position()
        self.crop_overlay.setGeometry(self.video.rect())
        if hasattr(self, "plugin_ui"):
            self.plugin_ui.position_overlays()

    def _auto_resize_for_media(self, info: dict[str, object]) -> None:
        source = str(info.get("source") or "")
        if not source or source == self._auto_resized_source:
            return
        if not bool(info.get("has_video")):
            self._auto_resized_source = source
            return
        if not bool(self.settings.get("playback.auto_resize", True)):
            return
        if self.isMaximized() or self.isFullScreen() or self._mini_mode or self._pip_mode:
            return
        aspect = self._media_aspect(info)
        if aspect <= 0:
            return
        self._auto_resized_source = source
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QRect(0, 0, *DEFAULT_WINDOW_SIZE)
        extra_width, extra_height = self._video_layout_extras()
        source_width = max(1, int(info.get("video_width") or 0))
        source_height = max(1, int(info.get("video_height") or 0))
        max_video_width = max(1, round(available.width() * 0.72) - extra_width)
        max_video_height = max(1, round(available.height() * 0.72) - extra_height)
        if source_width > 1 and source_height > 1:
            video_width = min(source_width, max_video_width)
            video_height = round(video_width / aspect)
        else:
            video_width = max_video_width
            video_height = round(video_width / aspect)
        if video_height > max_video_height:
            video_height = max_video_height
            video_width = round(video_height * aspect)
        target_width = max(MIN_WINDOW_SIZE[0], video_width + extra_width)
        target_height = max(MIN_WINDOW_SIZE[1], video_height + extra_height)
        center = self.frameGeometry().center()
        x = center.x() - target_width // 2
        y = center.y() - target_height // 2
        safe = self._safe_window_position(x, y, target_width, target_height, screen)
        self.setGeometry(safe.x(), safe.y(), target_width, target_height)

    def _prepare_geometry_for_source(self, source: str) -> None:
        """Compute a local file's final geometry before asking mpv to present it."""
        if source == self._auto_resized_source or not Path(source).is_file():
            return
        data = probe_media(source)
        aspect = video_aspect_from_probe(data)
        if aspect <= 0:
            return
        width = height = 0
        for stream in data.get("streams", []) if isinstance(data, dict) else []:
            if isinstance(stream, dict) and stream.get("codec_type") == "video":
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
                break
        self._auto_resize_for_media(
            {
                "source": source,
                "has_video": True,
                "video_width": width,
                "video_height": height,
                "video_aspect": aspect,
            }
        )

    @staticmethod
    def _media_aspect(info: dict[str, object]) -> float:
        try:
            aspect = float(info.get("video_aspect") or 0)
            if aspect > 0:
                return aspect
            width = float(info.get("video_width") or 0)
            height = float(info.get("video_height") or 0)
            return width / height if width > 0 and height > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0

    def _video_layout_extras(self) -> tuple[int, int]:
        extra_width = 0
        if hasattr(self, "sidebars"):
            if self.sidebars.playlist_open:
                extra_width += int(self.settings.get("ui.sidebar_width", 320))
            if self.sidebars.quick_pinned:
                extra_width += int(self.settings.get("ui.quick_settings_width", QUICK_SETTINGS_PANEL_WIDTH))
        # Top chrome and every OSC placement overlay the video. Only pinned
        # sidebars contribute persistent layout space.
        return extra_width, 0

    def _start_system_move(self, global_pos: QPoint | None = None) -> None:
        del global_pos
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _start_window_drag(self, global_pos: QPoint | None = None) -> None:
        """Route every title-like drag surface through the native move loop."""
        self._start_system_move(global_pos)

    def _move_window_drag(self, global_pos: QPoint | None = None) -> None:
        """The operating system owns movement after ``startSystemMove`` begins."""
        del global_pos

    def _restore_geometry(self) -> None:
        self.playlist_panel.set_side(str(self.settings.get("ui.sidebar_side", "right")))
        self.playlist_panel.set_current_tab(str(self.settings.get("ui.sidebar_tab", "playlist")))
        self.sidebars.restore_from_settings()
        width = int(self.settings.get("window.width", DEFAULT_WINDOW_SIZE[0]))
        height = int(self.settings.get("window.height", DEFAULT_WINDOW_SIZE[1]))
        compact_height = TITLE_BAR_HEIGHT + APP_MENU_HEIGHT + CONTROL_BAR_HEIGHT
        # Older compact-mode builds could persist the collapsed strip as the
        # normal geometry. Recover those installations on the next launch.
        if height <= compact_height:
            height = DEFAULT_WINDOW_SIZE[1]
            self.settings.set("window.height", height)
        x_value = self.settings.get("window.x")
        y_value = self.settings.get("window.y")
        preferred_screen = self._screen_by_name(str(self.settings.get("window.screen_name", "")))
        offset_x = self.settings.get("window.screen_offset_x")
        offset_y = self.settings.get("window.screen_offset_y")
        if preferred_screen is not None and offset_x is not None and offset_y is not None:
            available = preferred_screen.availableGeometry()
            x_value = available.left() + int(offset_x)
            y_value = available.top() + int(offset_y)
        saved_geometry = x_value is not None and y_value is not None
        if (
            not saved_geometry
            and self._initial_aspect > 0
            and bool(self.settings.get("playback.auto_resize", True))
        ):
            screen = preferred_screen or QApplication.primaryScreen()
            available = screen.availableGeometry() if screen is not None else QRect(0, 0, *DEFAULT_WINDOW_SIZE)
            extra_width, extra_height = self._video_layout_extras()
            video_width = max(1, round(available.width() * 0.72) - extra_width)
            video_height = round(video_width / self._initial_aspect)
            max_video_height = max(1, round(available.height() * 0.72) - extra_height)
            if video_height > max_video_height:
                video_height = max_video_height
                video_width = round(video_height * self._initial_aspect)
            width = max(MIN_WINDOW_SIZE[0], video_width + extra_width)
            height = max(MIN_WINDOW_SIZE[1], video_height + extra_height)
            x_value = available.center().x() - width // 2
            y_value = available.center().y() - height // 2
            self._auto_resized_source = self._initial_source
        width = max(width, MIN_WINDOW_SIZE[0])
        height = max(height, MIN_WINDOW_SIZE[1])
        if x_value is not None and y_value is not None:
            safe = self._safe_window_position(int(x_value), int(y_value), width, height, preferred_screen)
            self.setGeometry(safe.x(), safe.y(), width, height)
        else:
            self.resize(width, height)

    def _show_startup_window(self) -> None:
        if self.settings.get("window.maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._position_overlays()

    def _safe_window_position(self, x: int, y: int, width: int, height: int, preferred_screen: object | None = None) -> QPoint:
        if x <= -30000 or y <= -30000:
            return QPoint(80, 80)
        if preferred_screen is not None:
            available = preferred_screen.availableGeometry()
            safe_x = min(max(x, available.left()), max(available.left(), available.right() - width + 1))
            safe_y = min(max(y, available.top()), max(available.top(), available.bottom() - height + 1))
            return QPoint(safe_x, safe_y)
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

    def _screen_by_name(self, name: str) -> object | None:
        if not name:
            return None
        return next((screen for screen in QApplication.screens() if self._screen_identifier(screen) == name), None)

    @staticmethod
    def _screen_identifier(screen: object) -> str:
        parts = [
            str(getattr(screen, method)() or "")
            for method in ("name", "manufacturer", "model", "serialNumber")
            if callable(getattr(screen, method, None))
        ]
        identity = "|".join(part for part in parts if part)
        if identity:
            return identity
        screens = QApplication.screens()
        return f"screen-{screens.index(screen) if screen in screens else 0}"

    def _save_geometry(self) -> None:
        if self._mini_mode or self._pip_mode:
            snapshot = self.window_modes.compact_snapshot if self._mini_mode else self.window_modes.pip_snapshot
            if snapshot is None:
                return
            self.settings.set("window.maximized", snapshot.mode is WindowMode.MAXIMIZED)
            geometry = snapshot.geometry
            if geometry.isValid() and snapshot.mode is WindowMode.NORMAL:
                self.settings.set("window.width", geometry.width())
                self.settings.set("window.height", geometry.height())
                self.settings.set("window.x", geometry.x())
                self.settings.set("window.y", geometry.y())
        else:
            self.settings.set("window.maximized", self.isMaximized())
            geometry = self.normalGeometry() if self.isMaximized() or self.isFullScreen() else self.geometry()
            if not self.isMaximized() and not self.isFullScreen():
                self.settings.set("window.width", geometry.width())
                self.settings.set("window.height", geometry.height())
                self.settings.set("window.x", geometry.x())
                self.settings.set("window.y", geometry.y())
        if geometry.isValid():
            screen = QApplication.screenAt(geometry.center()) or self.screen() or QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                self.settings.set("window.screen_name", self._screen_identifier(screen))
                self.settings.set("window.screen_offset_x", geometry.x() - available.left())
                self.settings.set("window.screen_offset_y", geometry.y() - available.top())

    def _handle_window_edge_event(self, watched: object, event: QEvent) -> bool:
        if os.name == "nt":
            return False
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
            self._apply_pending_resize()
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
        aspect = self._media_aspect(self._last_media_info)
        aspect_lock = bool(self.settings.get("video.lock_resize_aspect", True))
        if aspect_lock and aspect > 0 and not self._mini_mode:
            geo = self._aspect_locked_geometry(geo, aspect, delta)
        min_width, min_height = self._resize_minimum_size()
        if geo.width() >= min_width and geo.height() >= min_height:
            self._pending_resize_geometry = geo
            if not self._interactive_resize_timer.isActive():
                self._interactive_resize_timer.start()

    def _aspect_locked_geometry(self, raw: QRect, aspect: float, delta: QPoint) -> QRect:
        original = QRect(self._resize_geometry)
        extra_width, extra_height = self._video_layout_extras()
        horizontal = "left" in self._resize_edge or "right" in self._resize_edge
        vertical = "top" in self._resize_edge or "bottom" in self._resize_edge
        drive_width = horizontal and (not vertical or abs(delta.x()) >= abs(delta.y()) * aspect)
        if drive_width:
            target_width = max(MIN_WINDOW_SIZE[0], raw.width())
            target_height = max(MIN_WINDOW_SIZE[1], round(max(1, target_width - extra_width) / aspect) + extra_height)
        else:
            target_height = max(MIN_WINDOW_SIZE[1], raw.height())
            target_width = max(MIN_WINDOW_SIZE[0], round(max(1, target_height - extra_height) * aspect) + extra_width)
        result = QRect(original)
        if "left" in self._resize_edge:
            result.setLeft(original.right() - target_width + 1)
        elif "right" in self._resize_edge:
            result.setRight(original.left() + target_width - 1)
        else:
            center_x = original.center().x()
            result.setLeft(center_x - target_width // 2)
            result.setWidth(target_width)
        if "top" in self._resize_edge:
            result.setTop(original.bottom() - target_height + 1)
        elif "bottom" in self._resize_edge:
            result.setBottom(original.top() + target_height - 1)
        else:
            center_y = original.center().y()
            result.setTop(center_y - target_height // 2)
            result.setHeight(target_height)
        return result

    def _apply_pending_resize(self) -> None:
        self._interactive_resize_timer.stop()
        geometry = self._pending_resize_geometry
        self._pending_resize_geometry = None
        if geometry is not None and geometry.isValid():
            self.setGeometry(geometry)

    def _resize_minimum_size(self) -> tuple[int, int]:
        if self._mini_mode:
            return 420, TITLE_BAR_HEIGHT + APP_MENU_HEIGHT + CONTROL_BAR_HEIGHT
        return MIN_WINDOW_SIZE
