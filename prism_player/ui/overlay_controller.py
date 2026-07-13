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

from config.settings import CONTROL_BAR_HEIGHT, PLAYLIST_PANEL_WIDTH, TITLE_BAR_HEIGHT

APP_MENU_HEIGHT = 32


class OverlayController(QObject):
    """Keep video geometry, chrome animation, and sidebar stacking together."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.animation: QParallelAnimationGroup | None = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

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
        if window.settings.get("ui.hide_controls_while_playing", True):
            configured = max(100, int(window.settings.get("ui.osc_hide_delay_ms", delay_ms)))
            self.hide_timer.start(configured)
        else:
            self.hide_timer.stop()
            if not window._chrome_visible:
                self.show()

    def show(self) -> None:
        self.animate(True)

    def hide(self) -> None:
        window = self.window
        if window._is_playing and not window._mini_mode and not window._pip_mode:
            self.animate(False)

    def animate(self, show: bool) -> None:
        window = self.window
        if window.central_shell is None or window.isMinimized():
            return
        if window._pip_mode:
            if window.app_menu_bar is not None:
                window.app_menu_bar.hide()
            window.title_bar.hide()
            window.control_bar.hide()
            return
        if window._mini_mode:
            window._chrome_visible = True
            if window.app_menu_bar is not None:
                window.app_menu_bar.show()
            window.title_bar.show()
            window.control_bar.show()
            window.title_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            window.control_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.position()
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
        osc_position = str(window.settings.get("ui.osc_position", "floating"))
        start_title = window.title_bar.geometry()
        start_menu = menu.geometry()
        start_control = window.control_bar.geometry()
        if not start_title.isValid() or start_title.width() != shell_rect.width():
            start_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        if not start_menu.isValid() or start_menu.width() != shell_rect.width():
            start_menu = QRect(0, TITLE_BAR_HEIGHT if show else -APP_MENU_HEIGHT, shell_rect.width(), APP_MENU_HEIGHT)
        if not start_control.isValid() or start_control.width() != shell_rect.width():
            y = shell_rect.height() - CONTROL_BAR_HEIGHT if show else shell_rect.height()
            start_control = QRect(0, y, shell_rect.width(), CONTROL_BAR_HEIGHT)
        target_title = QRect(0, 0 if show else -TITLE_BAR_HEIGHT, shell_rect.width(), TITLE_BAR_HEIGHT)
        target_menu = QRect(0, TITLE_BAR_HEIGHT if show else -APP_MENU_HEIGHT, shell_rect.width(), APP_MENU_HEIGHT)
        if osc_position == "top":
            target_control = QRect(0, TITLE_BAR_HEIGHT if show else -CONTROL_BAR_HEIGHT, shell_rect.width(), CONTROL_BAR_HEIGHT)
        else:
            target_control = QRect(0, shell_rect.height() - CONTROL_BAR_HEIGHT if show else shell_rect.height(), shell_rect.width(), CONTROL_BAR_HEIGHT)
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
        osc_position = str(window.settings.get("ui.osc_position", "floating"))
        if window._pip_mode:
            window.video.setGeometry(shell_rect)
            if menu is not None:
                menu.hide()
            window.title_bar.hide()
            window.control_bar.hide()
        elif window._mini_mode:
            window.video.setGeometry(QRect())
        elif osc_position == "bottom":
            window.video.setGeometry(0, TITLE_BAR_HEIGHT, shell_rect.width(), max(0, shell_rect.height() - TITLE_BAR_HEIGHT - CONTROL_BAR_HEIGHT))
        elif osc_position == "top":
            window.video.setGeometry(0, TITLE_BAR_HEIGHT + CONTROL_BAR_HEIGHT, shell_rect.width(), max(0, shell_rect.height() - TITLE_BAR_HEIGHT - CONTROL_BAR_HEIGHT))
        else:
            window.video.setGeometry(shell_rect)
        if self.animation is None and not window._pip_mode:
            if window._mini_mode:
                title_y = 0
                menu_y = TITLE_BAR_HEIGHT
                control_y = TITLE_BAR_HEIGHT + APP_MENU_HEIGHT
                window._chrome_visible = True
            else:
                title_y = 0 if window._chrome_visible else -TITLE_BAR_HEIGHT
                menu_y = TITLE_BAR_HEIGHT if window._chrome_visible else -APP_MENU_HEIGHT
                if osc_position == "top":
                    control_y = TITLE_BAR_HEIGHT if window._chrome_visible else -CONTROL_BAR_HEIGHT
                else:
                    control_y = shell_rect.height() - CONTROL_BAR_HEIGHT if window._chrome_visible else shell_rect.height()
            window.title_bar.setGeometry(0, title_y, shell_rect.width(), TITLE_BAR_HEIGHT)
            if menu is not None:
                menu.setGeometry(0, menu_y, shell_rect.width(), APP_MENU_HEIGHT)
            window.control_bar.setGeometry(0, control_y, shell_rect.width(), CONTROL_BAR_HEIGHT)
            chrome_visible = (window._chrome_visible or window._mini_mode) and not window.isMinimized()
            window.title_bar.setVisible(chrome_visible)
            window.control_bar.setVisible(chrome_visible)
            if menu is not None:
                menu.setVisible(chrome_visible and not window._pip_mode)
            if chrome_visible:
                self._raise_chrome()
        video_rect = window.video.rect()
        side = str(window.settings.get("ui.sidebar_side", "right"))
        panel_width = min(max(240, int(window.settings.get("ui.sidebar_width", PLAYLIST_PANEL_WIDTH))), min(600, video_rect.width()))
        panel_x = 0 if side == "left" else video_rect.width() - panel_width
        window.playlist_panel.set_side(side)
        panel_top_left = window.video.mapTo(shell, QPoint(panel_x, 0))
        window.playlist_panel.setGeometry(panel_top_left.x(), panel_top_left.y(), panel_width, video_rect.height())
        if window.playlist_panel.isVisible():
            window.playlist_panel.raise_()
            if window._chrome_visible:
                self._raise_chrome()
        window.drop_overlay.setGeometry(video_rect)
        window.buffering_indicator.adjustSize()
        window.buffering_indicator.move(
            (video_rect.width() - window.buffering_indicator.width()) // 2,
            (video_rect.height() - window.buffering_indicator.height()) // 2,
        )
        if window.osd.isVisible():
            window.osd.adjustSize()
            window.osd.move((video_rect.width() - window.osd.width()) // 2, max(56, video_rect.height() // 2 - 28))

    def _raise_chrome(self) -> None:
        window = self.window
        window.title_bar.raise_()
        if window.app_menu_bar is not None:
            window.app_menu_bar.raise_()
        window.control_bar.raise_()
