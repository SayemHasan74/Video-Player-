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
    dragStarted = pyqtSignal(QPoint)
    dragMoved = pyqtSignal(QPoint)
    dragEnded = pyqtSignal()
    keyPressed = pyqtSignal(object)
    frameReady = pyqtSignal()
    rendererReady = pyqtSignal()
    rendererDestroyed = pyqtSignal()
    rendererError = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self._backend: Any | None = None
        self._render_context: Any | None = None
        self._get_proc_address_callback: Any | None = None
        self._bound_context: QOpenGLContext | None = None
        self._renderer_generation = 0
        self._last_framebuffer_size = (0, 0)
        self._shutting_down = False
        self._left_press_global: QPoint | None = None
        self._dragging = False
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.frameReady.connect(self.update, Qt.ConnectionType.QueuedConnection)

    @property
    def renderer_active(self) -> bool:
        return self._render_context is not None

    @property
    def renderer_generation(self) -> int:
        return self._renderer_generation

    @property
    def framebuffer_size(self) -> tuple[int, int]:
        return self._last_framebuffer_size

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
        if context is not None and context is not self._bound_context:
            context.aboutToBeDestroyed.connect(
                self._context_about_to_be_destroyed,
                Qt.ConnectionType.DirectConnection,
            )
            self._bound_context = context
        self._initialize_renderer()

    def ensure_renderer(self) -> bool:
        """Recover a renderer if a platform replaced the GL context in a move."""
        if self._render_context is not None:
            self.update()
            return True
        if self._shutting_down or not self.isValid():
            return False
        made_current = False
        try:
            self.makeCurrent()
            made_current = True
            self._initialize_renderer()
        finally:
            if made_current:
                self.doneCurrent()
        self.update()
        return self._render_context is not None

    def _framebuffer_dimensions(self) -> tuple[int, int]:
        ratio = self.devicePixelRatioF()
        return (
            max(1, round(self.width() * ratio)),
            max(1, round(self.height() * ratio)),
        )

    def paintGL(self) -> None:
        if self._render_context is None or self._shutting_down:
            return
        width, height = self._framebuffer_dimensions()
        self._last_framebuffer_size = (width, height)
        try:
            self._render_context.render(
                opengl_fbo={
                    "fbo": self.defaultFramebufferObject(),
                    "w": width,
                    "h": height,
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
            self.rendererDestroyed.emit()
            if made_current:
                self.doneCurrent()
            if permanent:
                self._get_proc_address_callback = None

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
            self._renderer_generation += 1
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
        self._bound_context = None

    def resizeGL(self, _width: int, _height: int) -> None:
        self._last_framebuffer_size = self._framebuffer_dimensions()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.LeftButton:
            self._left_press_global = event.globalPosition().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._left_press_global is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if not self._dragging and (current - self._left_press_global).manhattanLength() >= 5:
                self._dragging = True
                self.dragStarted.emit(self._left_press_global)
            if self._dragging:
                self.dragMoved.emit(current)
        self.mousePositionChanged.emit(event.position().toPoint())
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._left_press_global is not None:
            if self._dragging:
                self.dragEnded.emit()
            else:
                self.clicked.emit()
            self._left_press_global = None
            self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.scrolled.emit(5 if event.angleDelta().y() > 0 else -5)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.keyPressed.emit(event)
        event.accept()
