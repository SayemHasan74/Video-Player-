"""OpenGL mpv render surface and user-input view."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QOpenGLContext, QWheelEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget


class VideoWidget(QOpenGLWidget):
    """Qt-owned OpenGL surface rendered by libmpv's render-context API."""

    doubleClicked = pyqtSignal()
    clicked = pyqtSignal()
    rightClicked = pyqtSignal(QPoint)
    middleClicked = pyqtSignal()
    scrolled = pyqtSignal(int)
    mouseMoved = pyqtSignal()
    mousePositionChanged = pyqtSignal(QPoint)
    keyPressed = pyqtSignal(object)
    frameReady = pyqtSignal()
    rendererReady = pyqtSignal()
    rendererError = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self._backend: Any | None = None
        self._render_context: Any | None = None
        self._get_proc_address_callback: Any | None = None
        self._shutting_down = False
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.frameReady.connect(self.update, Qt.ConnectionType.QueuedConnection)

    @property
    def renderer_active(self) -> bool:
        return self._render_context is not None

    def set_backend(self, backend: Any) -> None:
        """Attach the initialized player core before Qt creates the GL context."""
        self._backend = backend
        if self.isValid() and self._render_context is None:
            self.makeCurrent()
            try:
                self._initialize_renderer()
            finally:
                self.doneCurrent()

    def initializeGL(self) -> None:
        context = self.context()
        if context is not None:
            context.aboutToBeDestroyed.connect(
                self._context_about_to_be_destroyed,
                Qt.ConnectionType.DirectConnection,
            )
        self._initialize_renderer()

    def paintGL(self) -> None:
        if self._render_context is None or self._shutting_down:
            return
        ratio = self.devicePixelRatioF()
        try:
            self._render_context.render(
                opengl_fbo={
                    "fbo": self.defaultFramebufferObject(),
                    "w": max(1, round(self.width() * ratio)),
                    "h": max(1, round(self.height() * ratio)),
                },
                flip_y=True,
            )
            self._render_context.report_swap()
        except Exception as exc:
            self.logger.warning("mpv frame render failed: %s", exc)

    def shutdown_renderer(self, permanent: bool = True) -> None:
        """Free mpv GPU resources while Qt's GL context is still valid."""
        if self._render_context is None:
            if permanent:
                self._shutting_down = True
            return
        self._shutting_down = permanent
        try:
            self._render_context.update_cb = None
        except Exception:
            pass
        made_current = False
        try:
            if self.context() is not None and self.context().isValid():
                self.makeCurrent()
                made_current = True
            self._render_context.free()
        except Exception as exc:
            self.logger.debug("mpv renderer cleanup ignored: %s", exc)
        finally:
            self._render_context = None
            if made_current:
                self.doneCurrent()

    def _initialize_renderer(self) -> None:
        if self._render_context is not None or self._shutting_down:
            return
        player = getattr(self._backend, "mpv", None)
        if player is None:
            return
        try:
            from mpv import MpvGlGetProcAddressFn, MpvRenderContext

            self._get_proc_address_callback = MpvGlGetProcAddressFn(self._get_proc_address)
            self._render_context = MpvRenderContext(
                player,
                "opengl",
                opengl_init_params={"get_proc_address": self._get_proc_address_callback},
            )
            self._render_context.update_cb = self._request_frame
            self.rendererReady.emit()
        except Exception as exc:
            self._render_context = None
            self.logger.exception("Could not initialize mpv OpenGL renderer")
            self.rendererError.emit(f"OpenGL renderer could not start: {exc}")

    def _get_proc_address(self, _context: object, name: bytes) -> int:
        current = QOpenGLContext.currentContext()
        if current is None:
            return 0
        address = current.getProcAddress(name)
        return int(address) if address else 0

    def _request_frame(self) -> None:
        if not self._shutting_down:
            self.frameReady.emit()

    def _context_about_to_be_destroyed(self) -> None:
        self.shutdown_renderer(permanent=False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.mousePositionChanged.emit(event.position().toPoint())
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.scrolled.emit(5 if event.angleDelta().y() > 0 else -5)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.keyPressed.emit(event)
        event.accept()
