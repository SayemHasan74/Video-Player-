"""Shared sidebar layout, pinning, resizing, and animation ownership."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEasingCurve, QObject, QPoint, QRect, QTimer, QVariantAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from utils.accessibility import transitions_enabled
from ui.osc_layout_constants import QUICK_SETTINGS_PANEL_WIDTH, SIDEBAR_MINIMUM_WIDTH


class PinnedQuickSettingsDock(QFrame):
    """Container for the existing Quick Settings widget when pinned opposite."""

    unpinRequested = pyqtSignal()
    widthChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pinnedQuickSettings")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(SIDEBAR_MINIMUM_WIDTH)
        self.setMaximumWidth(600)
        self.setMouseTracking(True)
        self._side = "left"
        self._resizing = False
        self._resize_start = QPoint()
        self._resize_width = QUICK_SETTINGS_PANEL_WIDTH
        self._content: QWidget | None = None
        title = QLabel("Quick Settings")
        title.setStyleSheet("font-weight:600;color:#f0f0f0;")
        unpin = QPushButton("Unpin")
        unpin.clicked.connect(self.unpinRequested)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(unpin)
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(header)
        root.addLayout(self.content_layout, 1)
        self.setStyleSheet(
            "#pinnedQuickSettings{background:#0c0e12;border:1px solid #292b30;}"
            "#pinnedQuickSettings QPushButton{background:#17191d;border:1px solid #30343a;border-radius:5px;padding:5px 9px;}"
        )

    def attach(self, widget: QWidget) -> None:
        if self._content is widget:
            return
        if self._content is not None:
            self.content_layout.removeWidget(self._content)
        self._content = widget
        widget.setParent(self)
        self.content_layout.addWidget(widget)
        widget.show()

    def detach(self) -> QWidget | None:
        widget = self._content
        if widget is not None:
            self.content_layout.removeWidget(widget)
        self._content = None
        return widget

    def set_side(self, side: str) -> None:
        self._side = "left" if side == "left" else "right"

    def mousePressEvent(self, event: QMouseEvent) -> None:
        edge = event.position().x() >= self.width() - 5 if self._side == "left" else event.position().x() <= 5
        if event.button() == Qt.MouseButton.LeftButton and edge:
            self._resizing = True
            self._resize_start = event.globalPosition().toPoint()
            self._resize_width = self.width()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start.x()
            width = self._resize_width + delta if self._side == "left" else self._resize_width - delta
            self.widthChanged.emit(max(240, min(600, width)))
            event.accept()
            return
        edge = event.position().x() >= self.width() - 5 if self._side == "left" else event.position().x() <= 5
        self.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            self._resizing = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SidebarController(QObject):
    """Animate two shared side views and resize the video on every frame."""

    DURATION_MS = 210

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.quick_dock = PinnedQuickSettingsDock(window.central_shell)
        self.quick_dock.hide()
        if hasattr(window, "native_overlays"):
            window.native_overlays.register(self.quick_dock)
        self.playlist_open = False
        self.playlist_pinned = False
        self.quick_pinned = False
        self.playlist_progress = 0.0
        self.quick_progress = 0.0
        self._animations: dict[str, QVariantAnimation] = {}
        self._base_rect = QRect()
        self._suspended = False
        self._pending_playlist_width: int | None = None
        self._pending_quick_width: int | None = None
        self._width_timer = QTimer(self)
        self._width_timer.setSingleShot(True)
        self._width_timer.setInterval(16)
        self._width_timer.timeout.connect(self._apply_pending_widths)
        window.playlist_panel.playlistPinToggled.connect(self.set_playlist_pinned)
        window.playlist_panel.quickPinToggled.connect(self.set_quick_pinned)
        window.playlist_panel.widthChanged.connect(self.set_playlist_width)
        self.quick_dock.unpinRequested.connect(lambda: self.set_quick_pinned(False))
        self.quick_dock.widthChanged.connect(self.set_quick_width)

    def restore_from_settings(self) -> None:
        self.playlist_pinned = bool(self.window.settings.get("ui.playlist_pinned", False))
        self.window.playlist_panel.set_playlist_pinned(self.playlist_pinned)
        self.set_quick_pinned(
            bool(self.window.settings.get("ui.quick_settings_pinned", False)), animate=False
        )
        self.set_playlist_visible(
            bool(self.window.settings.get("ui.show_playlist", False)) or self.playlist_pinned,
            animate=False,
            persist=False,
        )

    def apply_preferences(self) -> None:
        requested_playlist_pin = bool(self.window.settings.get("ui.playlist_pinned", False))
        requested_quick_pin = bool(self.window.settings.get("ui.quick_settings_pinned", False))
        if requested_playlist_pin != self.playlist_pinned:
            self.set_playlist_pinned(requested_playlist_pin)
        if requested_quick_pin != self.quick_pinned:
            self.set_quick_pinned(requested_quick_pin)
        self.position(self._base_rect)

    def toggle_playlist(self) -> None:
        if self.playlist_open:
            if self.playlist_pinned:
                self.set_playlist_pinned(False)
            self.set_playlist_visible(False)
        else:
            self.set_playlist_visible(True)

    def request_close_playlist(self) -> None:
        if not self.playlist_pinned:
            self.set_playlist_visible(False)

    def set_playlist_visible(
        self, visible: bool, *, animate: bool = True, persist: bool = True
    ) -> None:
        visible = bool(visible)
        self.playlist_open = visible
        if persist:
            self.window.settings.set("ui.show_playlist", visible)
        self.window.control_bar.set_playlist_visible(visible)
        if visible:
            self.window.playlist_panel.show()
            self.window.playlist_panel.raise_()
            if hasattr(self.window, "native_overlays"):
                self.window.native_overlays.raise_widget(self.window.playlist_panel)
        self._transition("playlist", 1.0 if visible else 0.0, animate)

    def set_playlist_pinned(self, pinned: bool) -> None:
        self.playlist_pinned = bool(pinned)
        self.window.settings.set("ui.playlist_pinned", self.playlist_pinned)
        self.window.playlist_panel.set_playlist_pinned(self.playlist_pinned)
        if self.playlist_pinned:
            self.set_playlist_visible(True)
        else:
            self._refresh_geometry()

    def set_quick_pinned(self, pinned: bool, *, animate: bool = True) -> None:
        pinned = bool(pinned)
        if pinned == self.quick_pinned and (not pinned or self.quick_dock._content is not None):
            return
        self.quick_pinned = pinned
        self.window.settings.set("ui.quick_settings_pinned", pinned)
        if pinned:
            quick = self.window.playlist_panel.detach_quick_settings()
            self.quick_dock.attach(quick)
            self.quick_dock.show()
            self.quick_dock.raise_()
            if hasattr(self.window, "native_overlays"):
                self.window.native_overlays.raise_widget(self.quick_dock)
        self._transition("quick", 1.0 if pinned else 0.0, animate)

    def set_playlist_width(self, width: int) -> None:
        self._pending_playlist_width = max(240, min(600, int(width)))
        self.window.settings.set("ui.sidebar_width", self._pending_playlist_width)
        if not self._width_timer.isActive():
            self._width_timer.start()

    def set_quick_width(self, width: int) -> None:
        self._pending_quick_width = max(240, min(600, int(width)))
        self.window.settings.set("ui.quick_settings_width", self._pending_quick_width)
        if not self._width_timer.isActive():
            self._width_timer.start()

    def _apply_pending_widths(self) -> None:
        if self._pending_playlist_width is not None:
            self.window.settings.set("ui.sidebar_width", self._pending_playlist_width)
            self._pending_playlist_width = None
        if self._pending_quick_width is not None:
            self.window.settings.set("ui.quick_settings_width", self._pending_quick_width)
            self._pending_quick_width = None
        self._refresh_geometry()

    def suspend(self) -> None:
        self._suspended = True
        self.stop()
        self.quick_dock.hide()

    def resume(self) -> None:
        self._suspended = False

    def stop(self) -> None:
        for animation in self._animations.values():
            animation.stop()
            animation.deleteLater()
        self._animations.clear()

    def position(self, base_rect: QRect) -> None:
        if base_rect.isValid():
            self._base_rect = QRect(base_rect)
        if not self._base_rect.isValid() or self._suspended:
            return
        window = self.window
        base = self._base_rect
        side = "left" if str(window.settings.get("ui.sidebar_side", "right")) == "left" else "right"
        quick_side = "right" if side == "left" else "left"
        playlist_width = min(600, max(SIDEBAR_MINIMUM_WIDTH, int(window.settings.get("ui.sidebar_width", 320))))
        quick_width = min(600, max(SIDEBAR_MINIMUM_WIDTH, int(window.settings.get("ui.quick_settings_width", QUICK_SETTINGS_PANEL_WIDTH))))
        playlist_visible_width = round(playlist_width * self.playlist_progress)
        quick_visible_width = round(quick_width * self.quick_progress)

        # Every open sidebar is content geometry for aspect-lock purposes.
        # Reserving its visible width avoids computing the ratio against the
        # total frame, which distorts the video near the minimum window size.
        playlist_inset = playlist_visible_width
        left_inset = (playlist_inset if side == "left" else 0) + (quick_visible_width if quick_side == "left" else 0)
        right_inset = (playlist_inset if side == "right" else 0) + (quick_visible_width if quick_side == "right" else 0)
        video_width = max(1, base.width() - left_inset - right_inset)
        video_geometry = QRect(base.x() + left_inset, base.y(), video_width, base.height())
        if window.video.geometry() != video_geometry:
            window.video.setGeometry(video_geometry)

        playlist_x = base.x() - playlist_width + playlist_visible_width if side == "left" else base.x() + base.width() - playlist_visible_width
        quick_x = base.x() - quick_width + quick_visible_width if quick_side == "left" else base.x() + base.width() - quick_visible_width
        window.playlist_panel.set_side(side)
        window.playlist_panel.setGeometry(playlist_x, base.y(), playlist_width, base.height())
        self.quick_dock.set_side(quick_side)
        self.quick_dock.setGeometry(quick_x, base.y(), quick_width, base.height())
        if self.playlist_progress > 0:
            window.playlist_panel.show()
            window.playlist_panel.raise_()
            if hasattr(window, "native_overlays"):
                window.native_overlays.raise_widget(window.playlist_panel)
        if self.quick_progress > 0 and self.quick_dock._content is not None:
            self.quick_dock.show()
            self.quick_dock.raise_()
            if hasattr(window, "native_overlays"):
                window.native_overlays.raise_widget(self.quick_dock)

    def is_sidebar_widget(self, widget: QWidget | None) -> bool:
        while widget is not None:
            if widget in {self.window.playlist_panel, self.quick_dock}:
                return True
            widget = widget.parentWidget()
        return False

    def _transition(self, name: str, target: float, animate: bool) -> None:
        current = self.playlist_progress if name == "playlist" else self.quick_progress
        old = self._animations.pop(name, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        if not animate or not transitions_enabled(self.window.settings) or abs(current - target) < 0.001:
            self._set_progress(name, target)
            self._finish_transition(name, target)
            return
        animation = QVariantAnimation(self)
        animation.setDuration(self.DURATION_MS)
        animation.setStartValue(current)
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(lambda value, name=name: self._set_progress(name, float(value)))
        animation.finished.connect(lambda name=name, target=target: self._finish_transition(name, target))
        self._animations[name] = animation
        animation.start()

    def _set_progress(self, name: str, value: float) -> None:
        # Easing curves can spend their final frames infinitesimally short of
        # the endpoint under load. Pixel geometry has no useful distinction
        # there, so snap before rounding can leave a one-pixel edge strip.
        if value >= 0.995:
            value = 1.0
        elif value <= 0.005:
            value = 0.0
        if name == "playlist":
            self.playlist_progress = max(0.0, min(1.0, value))
        else:
            self.quick_progress = max(0.0, min(1.0, value))
        self._refresh_geometry()

    def _finish_transition(self, name: str, target: float) -> None:
        animation = self._animations.pop(name, None)
        if animation is not None:
            animation.deleteLater()
        # QVariantAnimation can emit its last frame just below the endpoint
        # (for example 0.9967) and then finish. Snap to the exact endpoint so
        # the panel never remains clipped a few pixels beyond the shell.
        if name == "playlist":
            self.playlist_progress = max(0.0, min(1.0, target))
        else:
            self.quick_progress = max(0.0, min(1.0, target))
        if name == "playlist" and target <= 0:
            self.window.playlist_panel.hide()
        elif name == "quick" and target <= 0:
            self.quick_dock.hide()
            quick = self.quick_dock.detach()
            if quick is not None:
                self.window.playlist_panel.attach_quick_settings()
        self._refresh_geometry()

    def _refresh_geometry(self) -> None:
        # Width dragging already has a stable base rect. Re-running the entire
        # overlay layout here needlessly touches title/menu/OSC geometry and,
        # historically, reset the video to full width before applying insets.
        if self._base_rect.isValid():
            self.position(self._base_rect)
        elif self.window.central_shell is not None and hasattr(self.window, "overlays"):
            self.window.overlays.position()
