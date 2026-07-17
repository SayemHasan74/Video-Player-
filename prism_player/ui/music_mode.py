"""Dedicated Music Mode view and transition policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QThread,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QMouseEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from core.mpv_properties import VID

from assets.icons import svg_icon
from config.settings import APP_SHORT_NAME
from core.cover_art import extract_cover_art
from ui.control_bar import IconButton
from ui.seekbar import SeekBar
from ui.volume_slider import VolumeWidget
from utils.time_utils import format_time_pair
from utils.accessibility import transitions_enabled


AUDIO_EXTENSIONS = frozenset(
    {
        ".aac", ".ac3", ".aiff", ".ape", ".dff", ".dsd", ".dsf",
        ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma",
    }
)


class CoverArtWorker(QThread):
    """Read cover bytes away from the UI thread."""

    ready = pyqtSignal(str, object)

    def __init__(self, source: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.source = source

    def run(self) -> None:
        data = extract_cover_art(self.source)
        if not self.isInterruptionRequested():
            self.ready.emit(self.source, data)


class CoverArtLabel(QLabel):
    """Aspect-preserving cover image fitted to the compact art panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_image_data(self, data: bytes | None) -> bool:
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            self._source = QPixmap()
            self.clear()
            return False
        self._source = pixmap
        self._rescale()
        return True

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        self.setPixmap(
            self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class MusicTitleBar(QFrame):
    """Small opaque title bar that keeps Music Mode independently movable."""

    minimizeClicked = pyqtSignal()
    restoreClicked = pyqtSignal()
    closeClicked = pyqtSignal()
    dragStarted = pyqtSignal(QPoint)
    dragMoved = pyqtSignal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("musicTitleBar")
        self.setFixedHeight(36)
        self._dragging = False
        logo = QLabel(self)
        logo.setPixmap(svg_icon("comet", "#f3f3f3", 17).pixmap(17, 17))
        self.caption = QLabel(f"{APP_SHORT_NAME}  •  Music Mode", self)
        self.caption.setStyleSheet("color:#ededed;font-weight:600;")
        self.minimize_button = self._button("minimize", "Minimize Music Mode")
        self.restore_button = self._button("restore", "Return to the main player")
        self.close_button = self._button("close", "Close player")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 0, 3, 0)
        layout.setSpacing(7)
        layout.addWidget(logo)
        layout.addWidget(self.caption)
        layout.addStretch(1)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.restore_button)
        layout.addWidget(self.close_button)
        self.minimize_button.clicked.connect(self.minimizeClicked)
        self.restore_button.clicked.connect(self.restoreClicked)
        self.close_button.clicked.connect(self.closeClicked)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.dragStarted.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self.dragMoved.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _button(self, icon: str, tooltip: str) -> QPushButton:
        button = QPushButton(self)
        button.setFixedSize(38, 30)
        button.setIcon(svg_icon(icon))
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button


class MusicModeView(QWidget):
    """Compact audio-focused layout sharing the live video and playlist views."""

    playPauseClicked = pyqtSignal()
    previousClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    seekPreviewRequested = pyqtSignal(float)
    seekRequested = pyqtSignal(float)
    volumeChanged = pyqtSignal(int)
    muteClicked = pyqtSignal()
    volumeWheel = pyqtSignal(int)
    playlistToggled = pyqtSignal()
    collapseToggled = pyqtSignal()
    minimizeClicked = pyqtSignal()
    restoreClicked = pyqtSignal()
    closeClicked = pyqtSignal()
    dragStarted = pyqtSignal(QPoint)
    dragMoved = pyqtSignal(QPoint)

    COLLAPSED_HEIGHT = 126
    BASE_HEIGHT_WITH_ART = 224
    BASE_HEIGHT_WITHOUT_ART = 180
    PLAYLIST_HEIGHT = 344

    def __init__(self, animations_enabled: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("musicModeView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)
        self.animations_enabled = animations_enabled
        self.show_art = True
        self.playlist_expanded = False
        self.collapsed = False
        self._has_visual = False
        self._has_cover = False
        self._controls_animation: QPropertyAnimation | None = None
        self._video_widget: QWidget | None = None
        self._playlist_widget: QWidget | None = None
        self.setStyleSheet(
            """
            #musicModeView { background:#0b0c0f; border:1px solid #24272d; }
            #musicTitleBar { background:#0d0d0d; border-bottom:1px solid #252525; }
            #musicTitleBar QPushButton { background:transparent;border:0;border-radius:0;padding:0; }
            #musicTitleBar QPushButton:hover { background:#242424; }
            #musicArt { background:#090a0c;border:1px solid #292c32;border-radius:8px; }
            #musicTransport { background:#0d0f12;border-top:1px solid #24272d; }
            QLabel { background:transparent; }
            """
        )

        self.title_bar = MusicTitleBar(self)
        self.title_bar.minimizeClicked.connect(self.minimizeClicked)
        self.title_bar.restoreClicked.connect(self.restoreClicked)
        self.title_bar.closeClicked.connect(self.closeClicked)
        self.title_bar.dragStarted.connect(self.dragStarted)
        self.title_bar.dragMoved.connect(self.dragMoved)

        self.art_host = QFrame(self)
        self.art_host.setObjectName("musicArt")
        self.art_host.setMinimumSize(118, 112)
        self.art_host.setMaximumWidth(180)
        self.art_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.art_stack = QStackedLayout(self.art_host)
        self.art_stack.setContentsMargins(1, 1, 1, 1)
        self.art_placeholder = QLabel(self.art_host)
        self.art_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_placeholder.setPixmap(svg_icon("audio_track", "#737985", 54).pixmap(54, 54))
        self.art_placeholder.setToolTip("No embedded album artwork")
        self.art_stack.addWidget(self.art_placeholder)
        self.cover_art = CoverArtLabel(self.art_host)
        self.cover_art.setToolTip("Embedded album artwork")
        self.art_stack.addWidget(self.cover_art)

        self.title_label = QLabel("Nothing playing", self)
        self.title_label.setWordWrap(False)
        self.title_label.setStyleSheet("color:#f5f5f5;font-size:18px;font-weight:650;")
        self.artist_label = QLabel("Unknown artist", self)
        self.artist_label.setStyleSheet("color:#c5c8ce;font-size:13px;")
        self.album_label = QLabel("", self)
        self.album_label.setStyleSheet("color:#858b95;font-size:12px;")
        metadata = QVBoxLayout()
        metadata.setContentsMargins(4, 8, 8, 8)
        metadata.setSpacing(5)
        metadata.addStretch(1)
        metadata.addWidget(self.title_label)
        metadata.addWidget(self.artist_label)
        metadata.addWidget(self.album_label)
        metadata.addStretch(1)
        self.body = QFrame(self)
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(12, 8, 12, 8)
        body_layout.setSpacing(14)
        body_layout.addWidget(self.art_host)
        body_layout.addLayout(metadata, 1)

        self.seekbar = SeekBar(self)
        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setMinimumWidth(96)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previous_button = self._icon_button("prev_track", "Previous")
        self.play_button = self._icon_button("play", "Play or pause")
        self.next_button = self._icon_button("next_track", "Next")
        self.volume = VolumeWidget(self)
        self.playlist_button = self._icon_button("playlist_toggle", "Expand playlist")
        self.collapse_button = QPushButton("Collapse", self)
        self.collapse_button.setToolTip("Collapse to the control strip")
        self.collapse_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        transport_row = QHBoxLayout()
        transport_row.setContentsMargins(0, 0, 0, 0)
        transport_row.setSpacing(4)
        transport_row.addWidget(self.previous_button)
        transport_row.addWidget(self.play_button)
        transport_row.addWidget(self.next_button)
        transport_row.addSpacing(8)
        transport_row.addWidget(self.time_label)
        transport_row.addStretch(1)
        transport_row.addWidget(self.volume)
        transport_row.addWidget(self.playlist_button)
        transport_row.addWidget(self.collapse_button)
        self.transport = QFrame(self)
        self.transport.setObjectName("musicTransport")
        transport_layout = QVBoxLayout(self.transport)
        transport_layout.setContentsMargins(12, 6, 12, 7)
        transport_layout.setSpacing(3)
        transport_layout.addWidget(self.seekbar)
        transport_layout.addLayout(transport_row)
        self.transport_effect = QGraphicsOpacityEffect(self.transport)
        self.transport_effect.setOpacity(1.0)
        self.transport.setGraphicsEffect(self.transport_effect)

        self.playlist_host = QFrame(self)
        self.playlist_layout = QVBoxLayout(self.playlist_host)
        self.playlist_layout.setContentsMargins(0, 0, 0, 0)
        self.playlist_layout.setSpacing(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.title_bar)
        root.addWidget(self.body, 1)
        root.addWidget(self.transport)
        root.addWidget(self.playlist_host)
        self.playlist_host.hide()

        self.seekbar.seekPreviewRequested.connect(self.seekPreviewRequested)
        self.seekbar.seekRequested.connect(self.seekRequested)
        self.previous_button.clicked.connect(self.previousClicked)
        self.play_button.clicked.connect(self.playPauseClicked)
        self.next_button.clicked.connect(self.nextClicked)
        self.volume.volumeChanged.connect(self.volumeChanged)
        self.volume.muteToggled.connect(self.muteClicked)
        self.volume.wheelAdjusted.connect(self.volumeWheel)
        self.playlist_button.clicked.connect(self.playlistToggled)
        self.collapse_button.clicked.connect(self.collapseToggled)

    def attach_video(self, video: QWidget) -> None:
        if self._video_widget is video:
            return
        if self._video_widget is not None:
            self.art_stack.removeWidget(self._video_widget)
        self._video_widget = video
        self.art_stack.addWidget(video)
        self._update_art_stack()

    def detach_video(self) -> QWidget | None:
        video = self._video_widget
        if video is not None:
            self.art_stack.removeWidget(video)
        self._video_widget = None
        self.art_stack.setCurrentWidget(self.art_placeholder)
        return video

    def attach_playlist(self, playlist: QWidget) -> None:
        if self._playlist_widget is playlist:
            return
        if self._playlist_widget is not None:
            self.playlist_layout.removeWidget(self._playlist_widget)
        self._playlist_widget = playlist
        self.playlist_layout.addWidget(playlist)
        self.set_playlist_expanded(self.playlist_expanded)

    def detach_playlist(self) -> QWidget | None:
        playlist = self._playlist_widget
        if playlist is not None:
            self.playlist_layout.removeWidget(playlist)
        self._playlist_widget = None
        self.playlist_host.hide()
        return playlist

    def set_metadata(self, title: str, artist: str = "", album: str = "") -> None:
        self.title_label.setText(title or "Unknown title")
        self.title_label.setToolTip(title or "")
        self.artist_label.setText(artist or "Unknown artist")
        self.artist_label.setToolTip(artist or "")
        self.album_label.setText(album or "")
        self.album_label.setToolTip(album or "")
        self.album_label.setVisible(bool(album))

    def set_media_visual(self, has_video: bool, has_album_art: bool) -> None:
        self._has_visual = bool(has_video or has_album_art)
        self._update_art_stack()

    def set_cover_art(self, data: bytes | None) -> bool:
        self._has_cover = self.cover_art.set_image_data(data)
        self._update_art_stack()
        return self._has_cover

    def clear_cover_art(self) -> None:
        self.set_cover_art(None)

    def set_show_art(self, visible: bool) -> None:
        self.show_art = bool(visible)
        self.art_host.setVisible(self.show_art and not self.collapsed)

    def set_playlist_expanded(self, expanded: bool) -> None:
        self.playlist_expanded = bool(expanded)
        visible = self.playlist_expanded and not self.collapsed and self._playlist_widget is not None
        self.playlist_host.setVisible(visible)
        if self._playlist_widget is not None:
            self._playlist_widget.setVisible(visible)
        color = "#f3f3f3" if self.playlist_expanded else "#c0c0c0"
        self.playlist_button.setIcon(svg_icon("playlist_toggle", color))
        self.playlist_button.setToolTip("Hide playlist" if self.playlist_expanded else "Expand playlist")

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = bool(collapsed)
        self.body.setVisible(not self.collapsed)
        self.art_host.setVisible(self.show_art and not self.collapsed)
        self.collapse_button.setText("Expand" if self.collapsed else "Collapse")
        self.set_playlist_expanded(self.playlist_expanded)

    def set_paused(self, paused: bool) -> None:
        self.play_button.set_icon_name("play" if paused else "pause")

    def set_time(self, position: float, duration: float) -> None:
        self.seekbar.set_duration(duration)
        self.seekbar.set_position(position)
        self.time_label.setText(format_time_pair(position, duration))

    def set_volume_state(self, volume: int, muted: bool) -> None:
        self.volume.set_volume_state(volume, muted)

    def preferred_height(self) -> int:
        if self.collapsed:
            return self.COLLAPSED_HEIGHT
        base = self.BASE_HEIGHT_WITH_ART if self.show_art else self.BASE_HEIGHT_WITHOUT_ART
        return base + (self.PLAYLIST_HEIGHT if self.playlist_expanded else 0)

    def reveal_controls(self) -> None:
        self._animate_controls(1.0)

    def stop_animation(self) -> None:
        if self._controls_animation is not None:
            self._controls_animation.stop()
            self._controls_animation.deleteLater()
            self._controls_animation = None

    def enterEvent(self, event: object) -> None:
        self._animate_controls(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:
        self._animate_controls(0.16)
        super().leaveEvent(event)

    def _animate_controls(self, opacity: float) -> None:
        self.stop_animation()
        if not self.animations_enabled:
            self.transport_effect.setOpacity(opacity)
            return
        animation = QPropertyAnimation(self.transport_effect, b"opacity", self)
        animation.setDuration(200)
        animation.setStartValue(self.transport_effect.opacity())
        animation.setEndValue(opacity)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: setattr(self, "_controls_animation", None))
        self._controls_animation = animation
        animation.start()

    def _update_art_stack(self) -> None:
        if self._has_cover:
            if self._video_widget is not None:
                self._video_widget.hide()
            self.art_stack.setCurrentWidget(self.cover_art)
        elif self._video_widget is not None and self._has_visual:
            self._video_widget.show()
            self.art_stack.setCurrentWidget(self._video_widget)
        else:
            if self._video_widget is not None:
                self._video_widget.hide()
            self.art_stack.setCurrentWidget(self.art_placeholder)

    def _icon_button(self, icon: str, tooltip: str) -> IconButton:
        button = IconButton(icon, tooltip, self)
        button.setFixedSize(34, 34)
        return button


class MusicModeController(QObject):
    """Coordinate Music Mode without creating another player or playlist model."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.view = MusicModeView(
            animations_enabled=transitions_enabled(window.settings),
            parent=window.central_shell,
        )
        self.view.hide()
        self._attached = False
        self._auto_entered = False
        self._last_media_info: dict[str, Any] = {}
        self._cover_source = ""
        self._cover_workers: set[CoverArtWorker] = set()
        self._playlist_maximum_width = 600
        self._connect_view()

    @property
    def manual_override(self) -> bool | None:
        return self.window.session.music_mode_manual_override

    def toggle_manual(self) -> None:
        if self.window.window_modes.is_compact:
            self.window.session.music_mode_manual_override = False
            self._auto_entered = False
            self.window.window_modes.exit_compact()
        else:
            self.window.session.music_mode_manual_override = True
            self._auto_entered = False
            self.window.window_modes.enter_compact()

    def enter_auto(self) -> None:
        if self.manual_override is False or self.window.window_modes.is_compact:
            return
        self._auto_entered = True
        self.window.window_modes.enter_compact()

    def source_loaded(self, source: str) -> None:
        self.view.clear_cover_art()
        self._cover_source = ""
        self.sync_current_item()
        if self.is_audio_extension(source):
            self._start_cover_art(source)
        if (
            self.manual_override is None
            and bool(self.window.settings.get("playback.auto_music_mode", True))
            and self.is_audio_extension(source)
        ):
            self.enter_auto()

    def media_info_changed(self, info: dict[str, Any]) -> None:
        source = str(info.get("source") or "")
        if source and source != self.window.player.current_source:
            return
        self._last_media_info = dict(info)
        current = self.window.playlist.current_item()
        title = str(info.get("title") or (current.title if current else ""))
        artist = str(info.get("artist") or (current.artist if current else ""))
        album = str(info.get("album") or (current.album if current else ""))
        self.view.set_metadata(title, artist, album)
        self.view.set_media_visual(bool(info.get("has_video")), False)
        if self.manual_override is not None or not self.window.settings.get("playback.auto_music_mode", True):
            return
        audio_only = self.is_audio_extension(source) or (
            bool(info.get("has_audio")) and not bool(info.get("has_video"))
        )
        if audio_only:
            self.window.player.set_property(VID, "no")
            self._start_cover_art(source)
            self.enter_auto()
        elif self._auto_entered and self.window.window_modes.is_compact:
            self._auto_entered = False
            self.window.window_modes.exit_compact()

    def metadata_ready(self, source: str, metadata: dict[str, Any]) -> None:
        current = self.window.playlist.current_item()
        if current is None or current.source != source:
            return
        self.view.set_metadata(
            str(metadata.get("title") or current.title),
            str(metadata.get("artist") or current.artist),
            str(metadata.get("album") or current.album),
        )

    def sync_current_item(self) -> None:
        current = self.window.playlist.current_item()
        if current is None:
            self.view.set_metadata("Nothing playing")
            return
        self.view.set_metadata(current.title, current.artist, current.album)

    def enter_layout(self) -> None:
        if self._attached:
            return
        window = self.window
        self.apply_preferences(resize=False)
        self._playlist_maximum_width = window.playlist_panel.maximumWidth()
        window.video.hide()
        window.playlist_panel.hide()
        window.video.setParent(self.view.art_host)
        self.view.attach_video(window.video)
        if hasattr(window.video, "ensure_renderer"):
            QTimer.singleShot(0, window.video.ensure_renderer)
        window.playlist_panel.setParent(self.view.playlist_host)
        window.playlist_panel.setMaximumWidth(16777215)
        self.view.attach_playlist(window.playlist_panel)
        self._attached = True
        self.sync_current_item()
        self.view.set_time(window.session.position, window.session.duration)
        self.view.set_paused(not window._is_playing)
        self.view.set_volume_state(
            int(getattr(window.player, "_volume", 80)),
            bool(getattr(window.player, "_muted", False)),
        )
        if self._last_media_info:
            self.media_info_changed(self._last_media_info)
        self.view.set_playlist_expanded(bool(window.settings.get("music_mode.show_playlist", False)))
        self.view.show()
        self.view.raise_()

    def exit_layout(self) -> None:
        if not self._attached:
            self.view.hide()
            return
        window = self.window
        window.video.hide()
        window.playlist_panel.hide()
        self.view.detach_video()
        self.view.detach_playlist()
        window.video.setParent(window.central_shell)
        window.playlist_panel.setParent(window.central_shell)
        window.playlist_panel.setMaximumWidth(self._playlist_maximum_width)
        window.video.show()
        if hasattr(window.video, "ensure_renderer"):
            QTimer.singleShot(0, window.video.ensure_renderer)
        self.view.hide()
        self._attached = False

    def position(self, rect: QRect) -> None:
        self.view.setGeometry(rect)
        self.view.raise_()
        video = self.window.video
        self.window.drop_overlay.setGeometry(video.rect())
        self.window.crop_overlay.setGeometry(video.rect())

    def target_height(self) -> int:
        return self.view.preferred_height()

    def toggle_playlist(self) -> None:
        self.set_playlist_expanded(not self.view.playlist_expanded)

    def set_playlist_expanded(self, expanded: bool) -> None:
        self.window.settings.set("music_mode.show_playlist", bool(expanded))
        self.view.set_playlist_expanded(expanded)
        if self.window.window_modes.is_compact:
            self._apply_target_height()

    def toggle_collapsed(self) -> None:
        self.view.set_collapsed(not self.view.collapsed)
        if self.window.window_modes.is_compact:
            self._apply_target_height()

    def apply_preferences(self, resize: bool = True) -> None:
        self.view.animations_enabled = transitions_enabled(self.window.settings)
        self.view.set_show_art(bool(self.window.settings.get("music_mode.show_album_art", True)))
        if self.window.window_modes.is_compact:
            self.view.set_playlist_expanded(bool(self.window.settings.get("music_mode.show_playlist", False)))
            if resize:
                self._apply_target_height()

    def reveal_controls(self) -> None:
        self.view.reveal_controls()

    def shutdown(self) -> None:
        workers = tuple(self._cover_workers)
        for worker in workers:
            if worker.isRunning():
                worker.requestInterruption()
        for worker in workers:
            if worker.isRunning():
                worker.wait(3000)
        self._cover_workers.clear()
        self.view.stop_animation()

    @staticmethod
    def is_audio_extension(source: str) -> bool:
        if not source or "://" in source:
            return False
        return Path(source).suffix.casefold() in AUDIO_EXTENSIONS

    def _apply_target_height(self) -> None:
        window = self.window
        height = self.target_height()
        geometry = QRect(window.geometry())
        window.setMaximumHeight(16777215)
        window.setMinimumSize(520, height)
        window.setMaximumHeight(height)
        window.setGeometry(geometry.left(), geometry.top(), max(520, geometry.width()), height)
        window._position_overlays()

    def _start_cover_art(self, source: str) -> None:
        if not source or "://" in source or source == self._cover_source:
            return
        self._cover_source = source
        for worker in tuple(self._cover_workers):
            if worker.isRunning():
                worker.requestInterruption()
        worker = CoverArtWorker(source, self)
        self._cover_workers.add(worker)
        worker.ready.connect(self._cover_art_ready)
        worker.finished.connect(lambda worker=worker: self._cover_worker_finished(worker))
        worker.start()

    def _cover_art_ready(self, source: str, data: bytes | None) -> None:
        if source != self.window.player.current_source:
            return
        self.view.set_cover_art(data)
        media_controls = getattr(self.window, "media_controls", None)
        if media_controls is not None:
            media_controls.update_artwork(data)

    def _cover_worker_finished(self, worker: CoverArtWorker) -> None:
        self._cover_workers.discard(worker)
        worker.deleteLater()

    def _connect_view(self) -> None:
        view = self.view
        window = self.window
        view.playPauseClicked.connect(lambda: window.trigger_action("play_pause"))
        view.previousClicked.connect(lambda: window.trigger_action("previous"))
        view.nextClicked.connect(lambda: window.trigger_action("next"))
        view.seekPreviewRequested.connect(window.playback_events.preview_seek_from_ui)
        view.seekRequested.connect(window.playback_events.seek_from_ui)
        view.volumeChanged.connect(window.playback_events.volume_from_ui)
        view.muteClicked.connect(window.player.toggle_mute)
        view.volumeWheel.connect(window.player.change_volume)
        view.playlistToggled.connect(self.toggle_playlist)
        view.collapseToggled.connect(self.toggle_collapsed)
        view.minimizeClicked.connect(window.showMinimized)
        view.restoreClicked.connect(self.toggle_manual)
        view.closeClicked.connect(window.close)
        view.dragStarted.connect(window._start_window_drag)
        view.dragMoved.connect(window._move_window_drag)
