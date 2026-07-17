"""Native QWindow OpenGL surface for libmpv's render API."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QExposeEvent,
    QKeyEvent,
    QMouseEvent,
    QOpenGLContext,
    QResizeEvent,
    QSurface,
    QSurfaceFormat,
    QWheelEvent,
    QWindow,
)

from core.mpv_engine import MpvEngine
from ui.video_area_input import drag_threshold_reached


class MpvRenderWindow(QWindow):
    """Own the native GL context and present mpv frames on Qt update requests."""

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
    rendererReady = pyqtSignal()
    rendererDestroyed = pyqtSignal()
    rendererError = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.setSurfaceType(QSurface.SurfaceType.OpenGLSurface)
        self.setFormat(QSurfaceFormat.defaultFormat())
        self._gl_context: QOpenGLContext | None = None
        self._engine: MpvEngine | None = None
        self._renderer_active = False
        self._renderer_generation = 0
        self._last_framebuffer_size = (0, 0)
        self._shutting_down = False
        self._left_press_global: QPoint | None = None
        self._dragging = False

    @property
    def renderer_active(self) -> bool:
        return self._renderer_active

    @property
    def renderer_generation(self) -> int:
        return self._renderer_generation

    @property
    def framebuffer_size(self) -> tuple[int, int]:
        return self._last_framebuffer_size

    def set_engine(self, engine: MpvEngine | None) -> None:
        if self._engine is engine:
            return
        if self._engine is not None:
            try:
                self._engine.signals.render_update.disconnect(self._request_render)
            except (TypeError, RuntimeError):
                pass
        self._engine = engine
        if engine is not None:
            engine.signals.render_update.connect(
                self._request_render,
                Qt.ConnectionType.QueuedConnection,
            )
        if self.isExposed():
            self.ensure_renderer()

    def _framebuffer_dimensions(self) -> tuple[int, int]:
        ratio = float(self.devicePixelRatio())
        return (
            max(1, round(self.width() * ratio)),
            max(1, round(self.height() * ratio)),
        )

    def exposeEvent(self, event: QExposeEvent) -> None:
        super().exposeEvent(event)
        if self.isExposed() and not self._shutting_down:
            self.ensure_renderer()
            self.requestUpdate()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._last_framebuffer_size = self._framebuffer_dimensions()
        if self.isExposed():
            self.requestUpdate()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.UpdateRequest:
            self._render_now()
            return True
        return super().event(event)

    @pyqtSlot()
    def _request_render(self) -> None:
        if not self._shutting_down:
            self.requestUpdate()

    def ensure_renderer(self) -> bool:
        if self._shutting_down or self._engine is None:
            return False
        self.create()
        if self._gl_context is None:
            context = QOpenGLContext(self)
            context.setFormat(self.requestedFormat())
            if not context.create():
                self.rendererError.emit("OpenGL context creation failed")
                return False
            context.aboutToBeDestroyed.connect(
                self._context_about_to_be_destroyed,
                Qt.ConnectionType.DirectConnection,
            )
            self._gl_context = context
        if not self._gl_context.makeCurrent(self):
            self.rendererError.emit("OpenGL context could not be made current")
            return False
        try:
            if not self._renderer_active:
                self._engine.create_render_context(self._get_proc_address)
                self._renderer_active = True
                self._renderer_generation += 1
                self.rendererReady.emit()
        except Exception as exc:
            self.logger.exception("Could not initialize mpv OpenGL renderer")
            self.rendererError.emit(f"OpenGL renderer could not start: {exc}")
            self._renderer_active = False
        finally:
            self._gl_context.doneCurrent()
        return self._renderer_active

    def _render_now(self) -> None:
        if not self.isExposed() or self._shutting_down or self._engine is None:
            return
        if not self._renderer_active and not self.ensure_renderer():
            return
        context = self._gl_context
        if context is None or not context.makeCurrent(self):
            return
        width, height = self._framebuffer_dimensions()
        self._last_framebuffer_size = (width, height)
        try:
            self._engine.render_frame(width, height)
            context.swapBuffers(self)
            self._engine.report_swap()
        except Exception as exc:
            self.logger.warning("mpv frame render failed: %s", exc)
        finally:
            context.doneCurrent()

    def _get_proc_address(self, _context: object, name: bytes) -> int:
        context = QOpenGLContext.currentContext()
        if context is None:
            return 0
        address = context.getProcAddress(name)
        return int(address) if address else 0

    def shutdown_renderer(self, permanent: bool = True) -> None:
        if permanent:
            self._shutting_down = True
        context = self._gl_context
        if self._renderer_active and self._engine is not None:
            made_current = bool(context and context.makeCurrent(self))
            try:
                self._engine.free_render_context()
            finally:
                if made_current and context is not None:
                    context.doneCurrent()
            self._renderer_active = False
            self.rendererDestroyed.emit()
        if permanent:
            self._gl_context = None

    @pyqtSlot()
    def _context_about_to_be_destroyed(self) -> None:
        self.shutdown_renderer(permanent=False)
        self._gl_context = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.requestActivate()
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
            if not self._dragging and drag_threshold_reached(self._left_press_global, current):
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
