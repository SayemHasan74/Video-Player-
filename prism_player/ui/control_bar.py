"""Bottom playback control overlay."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from assets.icons import svg_icon
from config.settings import CONTROL_BAR_HEIGHT, SPEED_STEPS
from ui.seekbar import SeekBar
from ui.volume_slider import VolumeWidget
from utils.time_utils import format_time_pair


class IconButton(QPushButton):
    """Small square icon button."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedSize(36, 36)
        self.setIcon(svg_icon(icon_name))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 0; padding: 0; outline: none; } "
            "QPushButton:hover { background: #242424; } "
            "QPushButton:pressed { background: #1a1a1a; }"
        )

    def set_icon_name(self, icon_name: str) -> None:
        self.icon_name = icon_name
        self.setIcon(svg_icon(icon_name))


class ControlBar(QWidget):
    """Playback controls that overlay the bottom of the video."""

    playPauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    previousClicked = pyqtSignal()
    seekRequested = pyqtSignal(float)
    volumeChanged = pyqtSignal(int)
    muteClicked = pyqtSignal()
    volumeWheel = pyqtSignal(int)
    speedChanged = pyqtSignal(float)
    abLoopClicked = pyqtSignal()
    screenshotClicked = pyqtSignal()
    subtitleClicked = pyqtSignal()
    audioClicked = pyqtSignal()
    playlistClicked = pyqtSignal()
    pipClicked = pyqtSignal()
    coverClicked = pyqtSignal()
    fullscreenClicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setMinimumHeight(CONTROL_BAR_HEIGHT)
        self.setMaximumHeight(CONTROL_BAR_HEIGHT)
        self.setStyleSheet(
            """
            ControlBar {
                background: #0d0d0d;
                border-top: 1px solid #252525;
            }
            QLabel { color: #b7b7b7; background: transparent; font-size: 12px; }
            ControlBar QPushButton {
                background: transparent;
                border: none;
                border-radius: 0;
                outline: none;
                padding: 0;
            }
            ControlBar QPushButton:hover { background: #242424; }
            ControlBar QPushButton:pressed { background: #1a1a1a; }
            ControlBar QSlider { outline: none; }
            """
        )
        self.position = 0.0
        self.duration = 0.0
        self.speed_index = SPEED_STEPS.index(1.0)
        self.seekbar = SeekBar(self)
        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setMinimumWidth(96)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previous_button = IconButton("prev_track", "Previous", self)
        self.play_button = IconButton("play", "Play or pause", self)
        self.next_button = IconButton("next_track", "Next", self)
        self.stop_button = IconButton("stop", "Stop", self)
        self.speed_button = QPushButton("1x", self)
        self.speed_button.setFixedSize(44, 36)
        self.speed_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speed_button.setStyleSheet(
            "QPushButton { background: #1a1a1a; border: none; border-radius: 4px; padding: 0; outline: none; } "
            "QPushButton:hover { background: #242424; }"
        )
        self.ab_button = IconButton("ab_loop", "Set A-B loop", self)
        self.screenshot_button = IconButton("screenshot", "Save screenshot", self)
        self.subtitle_button = IconButton("subtitle", "Subtitle tracks", self)
        self.audio_button = IconButton("audio_track", "Audio tracks", self)
        self.volume = VolumeWidget(self)
        self.playlist_button = IconButton("playlist_toggle", "Playlist", self)
        self.pip_button = IconButton("pip", "Picture in picture", self)
        self.cover_button = IconButton("cover", "Cover screen", self)
        self.fullscreen_button = IconButton("fullscreen", "Fullscreen", self)
        self._build_layout()
        self._connect_signals()
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.opacity.setOpacity(1.0)
        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)

    def set_time(self, position: float, duration: float) -> None:
        self.position = position
        self.duration = duration
        self.seekbar.set_duration(duration)
        self.seekbar.set_position(position)
        self.time_label.setText(format_time_pair(position, duration))

    def set_paused(self, paused: bool) -> None:
        self.play_button.set_icon_name("play" if paused else "pause")

    def set_volume_state(self, volume: int, muted: bool) -> None:
        self.volume.set_volume_state(volume, muted)

    def set_speed(self, speed: float) -> None:
        if speed in SPEED_STEPS:
            self.speed_index = SPEED_STEPS.index(speed)
        text = f"{speed:g}x"
        self.speed_button.setText(text)
        self.speed_button.setToolTip(f"Playback speed: {text}")

    def set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.set_icon_name("fullscreen_exit" if enabled else "fullscreen")

    def set_cover_mode(self, enabled: bool) -> None:
        self.cover_button.setIcon(svg_icon("cover", "#5e9bff" if enabled else "#c0c0c0"))
        self.cover_button.setToolTip("Fit video to screen" if enabled else "Cover whole screen")

    def set_playlist_visible(self, enabled: bool) -> None:
        color = "#5e9bff" if enabled else "#c0c0c0"
        self.playlist_button.setIcon(svg_icon("playlist_toggle", color))

    def set_ab_state(self, label: str, active: bool) -> None:
        self.ab_button.setIcon(svg_icon("ab_loop", "#5e9bff" if active else "#c0c0c0"))
        self.ab_button.setToolTip(label)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._update_responsive_visibility()
        super().resizeEvent(event)

    def _update_responsive_visibility(self) -> None:
        width = self.width()
        compact = width < 900
        minimal = width < 720
        narrow = width < 640
        tiny = width < 520
        very_tiny = width < 460
        for widget in (self.ab_button, self.screenshot_button, self.subtitle_button, self.audio_button, self.pip_button):
            widget.setVisible(not compact)
        for widget in (self.speed_button, self.cover_button):
            widget.setVisible(not minimal)
        for widget in (self.previous_button, self.next_button, self.stop_button, self.time_label):
            widget.setVisible(not narrow)
        self.playlist_button.setVisible(not tiny)
        if very_tiny:
            self.volume.slider.setVisible(False)
        else:
            self.volume.slider.setVisible(not compact or width >= 560)
        if width < 380:
            self.volume.setVisible(False)
        else:
            self.volume.setVisible(True)
        for widget in (self.play_button, self.fullscreen_button):
            widget.setVisible(True)

    def fade_to(self, opacity: float, duration: int) -> None:
        self.fade.stop()
        self.fade.setDuration(duration)
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(opacity)
        self.fade.start()

    def contextMenuEvent(self, event: object) -> None:
        menu = QMenu(self)
        for speed in SPEED_STEPS:
            action = menu.addAction(f"{speed:g}x")
            action.setCheckable(True)
            action.setChecked(speed == SPEED_STEPS[self.speed_index])
            action.triggered.connect(lambda checked=False, value=speed: self.speedChanged.emit(value))
        menu.exec(self.mapToGlobal(event.pos()))

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 5, 12, 5)
        root.setSpacing(4)
        root.addWidget(self.seekbar)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for widget in (self.previous_button, self.play_button, self.next_button, self.stop_button):
            row.addWidget(widget)
        row.addSpacing(8)
        row.addWidget(self.time_label)
        row.addStretch(1)
        for widget in (
            self.speed_button,
            self.ab_button,
            self.screenshot_button,
            self.subtitle_button,
            self.audio_button,
            self.volume,
            self.playlist_button,
            self.pip_button,
            self.cover_button,
            self.fullscreen_button,
        ):
            row.addWidget(widget)
        root.addLayout(row)

    def _connect_signals(self) -> None:
        self.seekbar.seekRequested.connect(self.seekRequested.emit)
        self.previous_button.clicked.connect(self.previousClicked.emit)
        self.play_button.clicked.connect(self.playPauseClicked.emit)
        self.next_button.clicked.connect(self.nextClicked.emit)
        self.stop_button.clicked.connect(self.stopClicked.emit)
        self.speed_button.clicked.connect(self._cycle_speed)
        self.ab_button.clicked.connect(self.abLoopClicked.emit)
        self.screenshot_button.clicked.connect(self.screenshotClicked.emit)
        self.subtitle_button.clicked.connect(self.subtitleClicked.emit)
        self.audio_button.clicked.connect(self.audioClicked.emit)
        self.volume.volumeChanged.connect(self.volumeChanged.emit)
        self.volume.muteToggled.connect(self.muteClicked.emit)
        self.volume.wheelAdjusted.connect(self.volumeWheel.emit)
        self.playlist_button.clicked.connect(self.playlistClicked.emit)
        self.pip_button.clicked.connect(self.pipClicked.emit)
        self.cover_button.clicked.connect(self.coverClicked.emit)
        self.fullscreen_button.clicked.connect(self.fullscreenClicked.emit)

    def _cycle_speed(self) -> None:
        self.speed_index = (self.speed_index + 1) % len(SPEED_STEPS)
        self.speedChanged.emit(SPEED_STEPS[self.speed_index])
