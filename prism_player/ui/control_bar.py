"""Reusable on-screen-controller fragments and three layout containers."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from assets.icons import svg_icon
from config.settings import SPEED_STEPS
from ui.osc_layout_constants import CONTROL_BAR_HEIGHT, FLOATING_OSC_HEIGHT
from ui.seekbar import SeekBar
from ui.volume_slider import VolumeWidget
from utils.time_utils import format_time


TOOLBAR_ACTIONS: dict[str, tuple[str, str]] = {
    "playlist": ("playlist_toggle", "Playlist"),
    "subtitle": ("subtitle", "Subtitle tracks"),
    "audio": ("audio_track", "Audio tracks"),
    "screenshot": ("screenshot", "Save screenshot"),
    "ab_loop": ("ab_loop", "Set A-B loop"),
    "pip": ("pip", "Picture in picture"),
    "music": ("music_mode", "Music Mode"),
    "cover": ("cover", "Cover screen"),
    "fullscreen": ("fullscreen", "Fullscreen"),
}
DEFAULT_TOOLBAR = list(TOOLBAR_ACTIONS)


class IconButton(QPushButton):
    """Small square icon button shared by every OSC layout."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self.setFixedSize(36, 36)
        self.setIcon(svg_icon(icon_name))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_icon_name(self, icon_name: str) -> None:
        self.icon_name = icon_name
        self.setIcon(svg_icon(icon_name))


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OscDragHandle(QFrame):
    """Small dedicated vertical drag affordance for the floating OSC."""

    dragged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("oscDragHandle")
        self.setFixedHeight(7)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._last_y: int | None = None
        self._press_y: int | None = None
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_y = event.globalPosition().toPoint().y()
            self._press_y = self._last_y
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_y is not None and event.buttons() & Qt.MouseButton.LeftButton:
            y = event.globalPosition().toPoint().y()
            if not self._dragging:
                if self._press_y is None or abs(y - self._press_y) < QApplication.startDragDistance():
                    event.accept()
                    return
                self._dragging = True
            self.dragged.emit(y - self._last_y)
            self._last_y = y
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._last_y = None
        self._press_y = None
        self._dragging = False
        super().mouseReleaseEvent(event)


class TimelineFragment(QWidget):
    """Seekbar, buffering/chapters, and independently readable time labels."""

    seekPreviewRequested = pyqtSignal(float)
    seekRequested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.position = 0.0
        self.duration = 0.0
        self.show_remaining = False
        self.elapsed = QLabel("00:00", self)
        self.elapsed.setMinimumWidth(54)
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seekbar = SeekBar(self)
        self.seekbar.setMinimumWidth(120)
        self.seekbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.end_time = ClickableLabel("00:00", self)
        self.end_time.setMinimumWidth(62)
        self.end_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.end_time.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_time.setToolTip("Click to toggle total and remaining time")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.elapsed)
        layout.addWidget(self.seekbar, 1)
        layout.addWidget(self.end_time)
        self.seekbar.seekPreviewRequested.connect(self.seekPreviewRequested)
        self.seekbar.seekRequested.connect(self.seekRequested)
        self.end_time.clicked.connect(self.toggle_remaining)

    def set_time(self, position: float, duration: float) -> None:
        self.position = max(0.0, float(position))
        self.duration = max(0.0, float(duration))
        self.seekbar.set_duration(self.duration)
        self.seekbar.set_position(self.position)
        self.elapsed.setText(format_time(self.position))
        self._update_end_label()

    def toggle_remaining(self) -> None:
        self.show_remaining = not self.show_remaining
        self._update_end_label()

    def _update_end_label(self) -> None:
        if self.show_remaining and self.duration > 0:
            self.end_time.setText(f"−{format_time(max(0.0, self.duration - self.position))}")
        else:
            self.end_time.setText(format_time(self.duration))


class TransportFragment(QWidget):
    """Previous/play/next/stop controls reused without recreation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.previous = IconButton("prev_track", "Previous", self)
        self.play = IconButton("play", "Play or pause", self)
        self.next = IconButton("next_track", "Next", self)
        self.stop = IconButton("stop", "Stop", self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        for button in (self.previous, self.play, self.next, self.stop):
            layout.addWidget(button)


class AudioFragment(QWidget):
    """Playback speed and volume fragment reused by all placements."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.speed = QPushButton("1x", self)
        self.speed.setFixedSize(44, 36)
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speed.setObjectName("oscSpeed")
        self.volume = VolumeWidget(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.speed)
        layout.addWidget(self.volume)


class ToolbarFragment(QWidget):
    """Reorderable selection of existing OSC action buttons."""

    def __init__(self, buttons: dict[str, IconButton], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons = buttons
        self.order: list[str] = []
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(1)

    def set_order(self, order: list[str]) -> list[str]:
        normalized: list[str] = []
        for action_id in order:
            if action_id in self.buttons and action_id not in normalized:
                normalized.append(action_id)
        if not normalized:
            normalized = DEFAULT_TOOLBAR.copy()
        while self.layout.count():
            self.layout.takeAt(0)
        for action_id, button in self.buttons.items():
            button.setVisible(action_id in normalized)
        for action_id in normalized:
            self.layout.addWidget(self.buttons[action_id])
        self.order = normalized
        return normalized


class ControlBar(QWidget):
    """One OSC state shared across true floating, top, and bottom layouts."""

    playPauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    previousClicked = pyqtSignal()
    seekPreviewRequested = pyqtSignal(float)
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
    musicClicked = pyqtSignal()
    coverClicked = pyqtSignal()
    fullscreenClicked = pyqtSignal()
    customizeRequested = pyqtSignal()
    floatingDragged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(CONTROL_BAR_HEIGHT)
        self.position = 0.0
        self.duration = 0.0
        self.speed_index = SPEED_STEPS.index(1.0)
        self.layout_mode = "floating"

        self.timeline = TimelineFragment(self)
        self.seekbar = self.timeline.seekbar
        self.elapsed_label = self.timeline.elapsed
        self.remaining_label = self.timeline.end_time
        self.time_label = self.remaining_label  # compatibility for existing integrations
        self.transport = TransportFragment(self)
        self.previous_button = self.transport.previous
        self.play_button = self.transport.play
        self.next_button = self.transport.next
        self.stop_button = self.transport.stop
        self.audio_controls = AudioFragment(self)
        self.speed_button = self.audio_controls.speed
        self.volume = self.audio_controls.volume

        self._toolbar_buttons = {
            action_id: IconButton(icon, tooltip, self)
            for action_id, (icon, tooltip) in TOOLBAR_ACTIONS.items()
        }
        self.playlist_button = self._toolbar_buttons["playlist"]
        self.subtitle_button = self._toolbar_buttons["subtitle"]
        self.audio_button = self._toolbar_buttons["audio"]
        self.screenshot_button = self._toolbar_buttons["screenshot"]
        self.ab_button = self._toolbar_buttons["ab_loop"]
        self.pip_button = self._toolbar_buttons["pip"]
        self.music_button = self._toolbar_buttons["music"]
        self.cover_button = self._toolbar_buttons["cover"]
        self.fullscreen_button = self._toolbar_buttons["fullscreen"]
        self.toolbar = ToolbarFragment(self._toolbar_buttons, self)
        self.drag_handle = OscDragHandle(self)
        self.drag_handle.dragged.connect(self.floatingDragged)

        self._root = QVBoxLayout(self)
        self._connect_signals()
        self.set_toolbar_order(DEFAULT_TOOLBAR)
        self.set_layout_mode("floating")

    def set_layout_mode(self, mode: str) -> None:
        mode = mode if mode in {"floating", "top", "bottom"} else "floating"
        self.layout_mode = mode
        self.setFixedHeight(FLOATING_OSC_HEIGHT if mode == "floating" else CONTROL_BAR_HEIGHT)
        button_size = 36 if mode == "floating" else 24
        for button in (
            self.previous_button, self.play_button, self.next_button, self.stop_button,
            *self._toolbar_buttons.values(),
        ):
            button.setFixedSize(button_size, button_size)
        self.speed_button.setFixedSize(44 if mode == "floating" else 32, button_size)
        self.setObjectName({"floating": "oscFloating", "top": "oscTop", "bottom": "oscBottom"}[mode])
        self._clear_layout(self._root)
        if mode == "floating":
            self._root.setContentsMargins(12, 1, 12, 5)
            self._root.setSpacing(1)
            self.drag_handle.show()
            self._root.addWidget(self.drag_handle)
            self._root.addWidget(self.timeline)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(self.transport)
            row.addStretch(1)
            row.addWidget(self.audio_controls)
            row.addWidget(self.toolbar)
            self._root.addLayout(row)
        else:
            self._root.setContentsMargins(10, 5, 10, 5)
            self._root.setSpacing(0)
            self.drag_handle.hide()
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(self.transport)
            row.addWidget(self.timeline, 1)
            row.addWidget(self.audio_controls)
            row.addWidget(self.toolbar)
            self._root.addLayout(row)
        self.setStyleSheet(self._stylesheet())
        self._update_responsive_visibility()

    def set_toolbar_order(self, order: list[str]) -> list[str]:
        normalized = self.toolbar.set_order(order)
        self._update_responsive_visibility()
        return normalized

    def set_scroll_enabled(self, enabled: bool) -> None:
        self.seekbar.set_scroll_enabled(enabled)
        self.volume.set_scroll_enabled(enabled)

    def set_time(self, position: float, duration: float) -> None:
        self.position = position
        self.duration = duration
        self.timeline.set_time(position, duration)

    def set_buffered_ranges(self, ranges: list[tuple[float, float]]) -> None:
        self.seekbar.set_buffered_ranges(ranges)

    def set_chapters(self, chapters: list[dict]) -> None:
        self.seekbar.set_chapters(chapters)

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
        self.cover_button.setIcon(svg_icon("cover", "#f3f3f3" if enabled else "#c0c0c0"))
        self.cover_button.setToolTip("Fit video to screen" if enabled else "Cover whole screen")

    def set_playlist_visible(self, enabled: bool) -> None:
        self.playlist_button.setIcon(svg_icon("playlist_toggle", "#f3f3f3" if enabled else "#c0c0c0"))

    def set_ab_state(self, label: str, active: bool) -> None:
        self.ab_button.setIcon(svg_icon("ab_loop", "#f3f3f3" if active else "#c0c0c0"))
        self.ab_button.setToolTip(label)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._update_responsive_visibility()
        super().resizeEvent(event)

    def contextMenuEvent(self, event: object) -> None:
        menu = QMenu(self)
        speed_menu = menu.addMenu("Playback Speed")
        for speed in SPEED_STEPS:
            action = speed_menu.addAction(f"{speed:g}x")
            action.setCheckable(True)
            action.setChecked(speed == SPEED_STEPS[self.speed_index])
            action.triggered.connect(lambda checked=False, value=speed: self.speedChanged.emit(value))
        menu.addSeparator()
        menu.addAction("Customize Toolbar…", self.customizeRequested.emit)
        menu.exec(event.globalPos())

    def _connect_signals(self) -> None:
        self.timeline.seekPreviewRequested.connect(self.seekPreviewRequested)
        self.timeline.seekRequested.connect(self.seekRequested)
        self.previous_button.clicked.connect(self.previousClicked)
        self.play_button.clicked.connect(self.playPauseClicked)
        self.next_button.clicked.connect(self.nextClicked)
        self.stop_button.clicked.connect(self.stopClicked)
        self.speed_button.clicked.connect(self._cycle_speed)
        self.ab_button.clicked.connect(self.abLoopClicked)
        self.screenshot_button.clicked.connect(self.screenshotClicked)
        self.subtitle_button.clicked.connect(self.subtitleClicked)
        self.audio_button.clicked.connect(self.audioClicked)
        self.volume.volumeChanged.connect(self.volumeChanged)
        self.volume.muteToggled.connect(self.muteClicked)
        self.volume.wheelAdjusted.connect(self.volumeWheel)
        self.playlist_button.clicked.connect(self.playlistClicked)
        self.pip_button.clicked.connect(self.pipClicked)
        self.music_button.clicked.connect(self.musicClicked)
        self.cover_button.clicked.connect(self.coverClicked)
        self.fullscreen_button.clicked.connect(self.fullscreenClicked)

    def _cycle_speed(self) -> None:
        self.speed_index = (self.speed_index + 1) % len(SPEED_STEPS)
        self.speedChanged.emit(SPEED_STEPS[self.speed_index])

    def _update_responsive_visibility(self) -> None:
        width = self.width()
        self.stop_button.setVisible(width >= 590)
        self.elapsed_label.setVisible(width >= 520)
        self.remaining_label.setVisible(width >= 520)
        self.speed_button.setVisible(width >= 620)
        self.volume.slider.setVisible(width >= 720)
        active = self.toolbar.order
        limit = len(active) if width >= 900 else 5 if width >= 720 else 3 if width >= 560 else 1
        for index, action_id in enumerate(active):
            self._toolbar_buttons[action_id].setVisible(index < limit)
        self.play_button.show()

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child = item.layout()
            if child is not None:
                while child.count():
                    child.takeAt(0)
                child.deleteLater()

    def _stylesheet(self) -> str:
        return """
        #oscFloating { background: rgba(13,14,17,242); border:1px solid #343840; border-radius:12px; }
        #oscTop { background:#0d0d0d; border-bottom:1px solid #292929; border-radius:0; }
        #oscBottom { background:#0d0d0d; border-top:1px solid #292929; border-radius:0; }
        #oscDragHandle { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 transparent,stop:.42 #555b65,stop:.58 #555b65,stop:1 transparent); border-radius:2px; }
        ControlBar QLabel, TimelineFragment QLabel { color:#bfc3ca; background:transparent; font-size:11px; }
        ControlBar QPushButton { background:transparent; border:0; border-radius:5px; outline:none; padding:0; }
        ControlBar QPushButton:hover { background:#272a2f; }
        ControlBar QPushButton:pressed { background:#181a1e; }
        ControlBar QPushButton#oscSpeed { background:#1a1c20; }
        """
