"""Layout and animation ownership for in-window player overlays."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
)

from core.preferences import (
    ENABLE_TITLE_BAR_AND_OSC,
    OSC_HIDE_DELAY_MS,
    OSC_POSITION,
)
from ui.osc_layout_constants import (
    APP_MENU_HEIGHT,
    FLOATING_OSC_BOTTOM_MARGIN,
    FLOATING_OSC_MAX_WIDTH,
    FLOATING_OSC_MIN_WIDTH,
    FLOATING_OSC_TOP_BAND,
    TITLE_BAR_HEIGHT,
    TOP_OSC_MARGIN_FULLSCREEN,
    TOP_OSC_MARGIN_NORMAL,
)
from utils.accessibility import transitions_enabled


class OverlayController(QObject):
    """Keep video geometry, chrome animation, and sidebar stacking together."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.animation: QParallelAnimationGroup | None = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._timer_fired)
        self._momentary = False

    def _timer_fired(self) -> None:
        if self._momentary:
            self._momentary = False
            self.animate(False)
        else:
            self.hide()

    def stop_transients(self) -> None:
        self.hide_timer.stop()
        if self.animation is not None:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None

    def schedule_hide(self, delay_ms: int) -> None:
        window = self.window
        if window._mini_mode or window._pip_mode:
            return
        if not window.settings.get(ENABLE_TITLE_BAR_AND_OSC, True):
            self.animate(False)
            return
        if window.settings.get("ui.osc_always_visible", False):
            self.hide_timer.stop()
            if not window._chrome_visible:
                self.show()
        elif window.settings.get("ui.hide_controls_while_playing", True):
            configured = max(100, int(window.settings.get(OSC_HIDE_DELAY_MS, delay_ms)))
            self.hide_timer.start(configured)
        else:
            self.hide_timer.stop()
            if not window._chrome_visible:
                self.show()

    def show(self) -> None:
        self._momentary = False
        self.animate(True)

    def show_momentarily(self) -> None:
        if not self.window.settings.get(ENABLE_TITLE_BAR_AND_OSC, True):
            return
        self.animate(True)
        self._momentary = True
        delay = max(100, int(self.window.settings.get(OSC_HIDE_DELAY_MS, 3000)))
        self.hide_timer.start(delay)

    def hide(self) -> None:
        window = self.window
        if (
            window._is_playing
            and not window._mini_mode
            and not window._pip_mode
            and not window.settings.get("ui.osc_always_visible", False)
        ):
            self.animate(False)

    def move_floating(self, delta_y: int) -> None:
        """Move the floating OSC vertically while keeping it inside the video."""
        window = self.window
        if str(window.settings.get(OSC_POSITION, "floating")) != "floating":
            return
        maximum = max(0, window.central_shell.height() - window.control_bar.height() - FLOATING_OSC_TOP_BAND)
        current = int(window.settings.get("ui.osc_floating_offset", 0))
        window.settings.set("ui.osc_floating_offset", max(0, min(maximum, current - int(delta_y))))
        self.position()

    def animate(self, show: bool) -> None:
        window = self.window
        if window.central_shell is None or window.isMinimized():
            return
        if not window.settings.get(ENABLE_TITLE_BAR_AND_OSC, True):
            show = False
        if window._pip_mode:
            window._set_top_chrome_reserved(False)
            if window.app_menu_bar is not None:
                window.app_menu_bar.hide()
            window.title_bar.hide()
            window.control_bar.hide()
            return
        if window._mini_mode:
            window._set_top_chrome_reserved(False)
            if window.app_menu_bar is not None:
                window.app_menu_bar.hide()
            window.title_bar.hide()
            window.control_bar.hide()
            window.music_mode.reveal_controls()
            self.position()
            window._update_cursor_visibility()
            return
        if not transitions_enabled(window.settings):
            window._chrome_visible = show
            window._set_top_chrome_reserved(
                bool(window.settings.get(ENABLE_TITLE_BAR_AND_OSC, True))
            )
            if window.app_menu_bar is not None:
                window.app_menu_bar.setVisible(show)
            window.title_bar.setVisible(show)
            window.control_bar.setVisible(show)
            window.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
            window.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
            self.position()
            window._update_cursor_visibility()
            return
        if window._chrome_visible == show and self.animation is None:
            return
        if self.animation is not None:
            self.animation.stop()
        window._chrome_visible = show
        if show and window.app_menu_bar is not None:
            window.app_menu_bar.show()
        shell_rect = window.central_shell.rect()
        menu = window.app_menu_bar
        if menu is None:
            self.position()
            return
        start_title = window.title_bar.geometry()
        start_menu = menu.geometry()
        start_control = window.control_bar.geometry()
        if not start_title.isValid() or start_title.width() != shell_rect.width():
            start_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        if not start_menu.isValid() or start_menu.width() != shell_rect.width():
            start_menu = QRect(0, TITLE_BAR_HEIGHT if show else -APP_MENU_HEIGHT, shell_rect.width(), APP_MENU_HEIGHT)
        if not start_control.isValid():
            start_control = self._control_geometry(show)
        target_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        target_menu = QRect(0, TITLE_BAR_HEIGHT if show else -APP_MENU_HEIGHT, shell_rect.width(), APP_MENU_HEIGHT)
        target_control = self._control_geometry(show)
        window.title_bar.show()
        window.control_bar.show()
        window.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
        window.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)
        self._raise_chrome()
        group = QParallelAnimationGroup(self)
        for widget, start, target in (
            (window.title_bar, start_title, target_title),
            (menu, start_menu, target_menu),
            (window.control_bar, start_control, target_control),
        ):
            animation = QPropertyAnimation(widget, b"geometry", group)
            animation.setDuration(180 if show else 220)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic if show else QEasingCurve.Type.InCubic)
            animation.setStartValue(start)
            animation.setEndValue(target)
            group.addAnimation(animation)

        def finish() -> None:
            if not show:
                menu.hide()
                window.title_bar.hide()
                window.control_bar.hide()
            else:
                window.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                window.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self._raise_chrome()
            window._update_cursor_visibility()
            self.animation = None

        group.finished.connect(finish)
        self.animation = group
        group.start()

    def position(self) -> None:
        window = self.window
        shell = window.central_shell
        if shell is None:
            return
        shell_rect = shell.rect()
        menu = window.app_menu_bar
        osc_position = str(window.settings.get(OSC_POSITION, "floating"))
        show_top_chrome = bool(window.settings.get(ENABLE_TITLE_BAR_AND_OSC, True))
        window._set_top_chrome_reserved(
            show_top_chrome and not window._pip_mode and not window._mini_mode
        )
        base_video_rect = QRect(shell_rect)
        if window._pip_mode:
            window.video.setGeometry(base_video_rect)
            if hasattr(window, "sidebars"):
                window.sidebars.suspend()
            if menu is not None:
                menu.hide()
            window.title_bar.hide()
            window.control_bar.hide()
        elif window._mini_mode:
            if hasattr(window, "sidebars"):
                window.sidebars.suspend()
            window.music_mode.position(shell_rect)
        elif osc_position == "bottom":
            # Reserve one stable dock strip even while the OSC is hidden. This
            # prevents the libmpv render surface from resizing on every reveal.
            base_video_rect.setHeight(
                max(0, base_video_rect.height() - window.control_bar.height())
            )
        # In the normal window modes SidebarController is the sole owner of
        # video geometry.  Setting the full-width rectangle here and the
        # sidebar-adjusted rectangle a few lines later caused a visible
        # full-width -> inset-width stretch on every drag/animation frame.
        if self.animation is None and not window._pip_mode:
            if window._mini_mode:
                window.title_bar.hide()
                window.control_bar.hide()
                if menu is not None:
                    menu.hide()
            else:
                title_y = 0 if window._chrome_visible else -TITLE_BAR_HEIGHT
                menu_y = TITLE_BAR_HEIGHT if window._chrome_visible else -APP_MENU_HEIGHT
                chrome_width = window.width()
                window.title_bar.setGeometry(0, title_y, chrome_width, TITLE_BAR_HEIGHT)
                if menu is not None:
                    menu.setGeometry(0, menu_y, chrome_width, APP_MENU_HEIGHT)
                window.control_bar.setGeometry(self._control_geometry(window._chrome_visible))
                chrome_visible = window._chrome_visible and not window.isMinimized()
                window.title_bar.setVisible(chrome_visible)
                window.control_bar.setVisible(chrome_visible)
                if menu is not None:
                    menu.setVisible(chrome_visible and not window._pip_mode)
                if chrome_visible:
                    self._raise_chrome()
        if window._mini_mode:
            return
        if not window._pip_mode and hasattr(window, "sidebars"):
            window.sidebars.resume()
            window.sidebars.position(base_video_rect)
        elif not window._pip_mode:
            window.video.setGeometry(base_video_rect)
        video_rect = window.video.rect()
        if window._chrome_visible:
            self._raise_chrome()
        window.drop_overlay.setGeometry(video_rect)
        window.buffering_indicator.adjustSize()
        window.buffering_indicator.move(
            (video_rect.width() - window.buffering_indicator.width()) // 2,
            (video_rect.height() - window.buffering_indicator.height()) // 2,
        )
        if window.osd.isVisible():
            window.osd.reposition()
        if hasattr(window, "native_overlays"):
            window.native_overlays.raise_all()

    def _raise_chrome(self) -> None:
        window = self.window
        window.title_bar.raise_()
        if window.app_menu_bar is not None:
            window.app_menu_bar.raise_()
        window.control_bar.raise_()
        if hasattr(window, "native_overlays"):
            window.native_overlays.raise_widget(window.control_bar)

    def _control_geometry(self, visible: bool) -> QRect:
        window = self.window
        shell = window.central_shell
        if shell is None:
            return QRect()
        rect = shell.rect()
        mode = str(window.settings.get(OSC_POSITION, "floating"))
        height = window.control_bar.height()
        if mode == "floating":
            available_width = max(1, rect.width() - 32)
            width = min(FLOATING_OSC_MAX_WIDTH, max(FLOATING_OSC_MIN_WIDTH, available_width))
            width = min(width, available_width)
            x = max(0, (rect.width() - width) // 2)
            offset = max(0, int(window.settings.get("ui.osc_floating_offset", 0)))
            y = rect.height() - height - FLOATING_OSC_BOTTOM_MARGIN - offset if visible else rect.height() + 4
            return QRect(x, y, width, height)
        if mode == "top":
            margin = TOP_OSC_MARGIN_FULLSCREEN if window.isFullScreen() else TOP_OSC_MARGIN_NORMAL
            y = margin if visible else -height
            return QRect(0, y, rect.width(), height)
        y = rect.height() - height if visible else rect.height()
        return QRect(0, y, rect.width(), height)
