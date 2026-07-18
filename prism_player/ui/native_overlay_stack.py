"""Keep QWidget chrome above the embedded native video window on Windows."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Iterable

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget


_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010


class NativeOverlayStack(QObject):
    """Promote overlay roots to native siblings and maintain their HWND order.

    ``QWidget.createWindowContainer()`` embeds the mpv ``QWindow`` as an
    opaque native child window. Ordinary alien QWidgets cannot stack above
    that child on Windows. Giving only each overlay *root* its own child HWND
    preserves the existing QWidget controls while placing them in the same
    native Z-order domain as the render window.
    """

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self._owner = owner
        self._widgets: list[QWidget] = []
        self._surface: QObject | None = None
        self._raise_queued = False
        self.enabled = sys.platform == "win32" and QGuiApplication.platformName() != "offscreen"
        self._set_window_pos = None
        if self.enabled:
            function = ctypes.windll.user32.SetWindowPos
            function.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            function.restype = wintypes.BOOL
            self._set_window_pos = function
        owner.installEventFilter(self)

    def watch_surface(self, surface: QObject | None) -> None:
        """Reassert overlays when the embedded render surface is exposed."""
        if self._surface is surface:
            return
        if self._surface is not None:
            self._surface.removeEventFilter(self)
        self._surface = surface
        if surface is not None:
            surface.installEventFilter(self)

    def register(self, widget: QWidget | None) -> None:
        if widget is None or widget in self._widgets:
            return
        self._widgets.append(widget)
        widget.installEventFilter(self)
        if not self.enabled:
            return
        widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        # Materialize the HWND now, before the render child can establish an
        # opaque Z-order above it during the first expose event.
        widget.winId()
        self.raise_widget(widget)

    def register_many(self, widgets: Iterable[QWidget | None]) -> None:
        for widget in widgets:
            self.register(widget)

    def unregister(self, widget: QWidget) -> None:
        if widget in self._widgets:
            self._widgets.remove(widget)
            widget.removeEventFilter(self)

    def is_registered(self, widget: QWidget) -> bool:
        return widget in self._widgets

    def raise_widget(self, widget: QWidget | None) -> None:
        if (
            widget is None
            or widget not in self._widgets
            or not self.enabled
            or not widget.isVisible()
        ):
            return
        widget.raise_()
        assert self._set_window_pos is not None
        self._set_window_pos(
            wintypes.HWND(int(widget.winId())),
            wintypes.HWND(0),
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )

    def raise_all(self) -> None:
        if not self.enabled:
            return
        for widget in tuple(self._widgets):
            if widget.isVisible():
                self.raise_widget(widget)

    def raise_all_deferred(self) -> None:
        if self._raise_queued:
            return
        self._raise_queued = True

        def promote() -> None:
            self._raise_queued = False
            self.raise_all()

        QTimer.singleShot(0, promote)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._owner and event.type() in {
            QEvent.Type.Show,
            QEvent.Type.WindowActivate,
            QEvent.Type.WindowStateChange,
        }:
            self.raise_all_deferred()
        elif watched is self._surface and event.type() in {
            QEvent.Type.Expose,
            QEvent.Type.Show,
            QEvent.Type.PlatformSurface,
        }:
            self.raise_all_deferred()
        if (
            self.enabled
            and isinstance(watched, QWidget)
            and event.type() in {QEvent.Type.Show, QEvent.Type.ParentChange, QEvent.Type.WinIdChange}
        ):
            # Qt may finish creating/reparenting the native child after the
            # event is delivered. Reassert its Z-order on the next GUI turn.
            QTimer.singleShot(0, lambda widget=watched: self.raise_widget(widget))
        return False
