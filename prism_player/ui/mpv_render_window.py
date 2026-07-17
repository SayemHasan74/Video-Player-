"""Native QWindow surface with rendering owned by a dedicated thread."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QPoint, Qt, pyqtSignal, pyqtSlot
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
from ui.mpv_render_thread import MpvRenderThread
from ui.video_area_input import drag_threshold_reached


class MpvRenderWindow(QWindow):
    """Own the native surface and hand all GL presentation to its worker."""

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
        self._share_context: QOpenGLContext | None = None
        self._render_thread: MpvRenderThread | None = None
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
            self.shutdown_renderer(permanent=False)
        self._engine = engine
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
        if self._render_thread is not None:
            self._render_thread.set_exposed(self.isExposed())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._last_framebuffer_size = self._framebuffer_dimensions()
        if self._render_thread is not None:
            self._render_thread.set_framebuffer_size(*self._last_framebuffer_size)

    @pyqtSlot()
    def _request_render(self) -> None:
        thread = self._render_thread
        if not self._shutting_down and thread is not None:
            thread.request_frame()

    def ensure_renderer(self) -> bool:
        if self._shutting_down or self._engine is None:
            return False
        if self._render_thread is not None and self._render_thread.isRunning():
            return True
        self.create()
        if self._share_context is None:
            context = QOpenGLContext(self)
            context.setFormat(self.requestedFormat())
            if not context.create():
                self.rendererError.emit("OpenGL context creation failed")
                return False
            context.aboutToBeDestroyed.connect(
                self._context_about_to_be_destroyed,
                Qt.ConnectionType.DirectConnection,
            )
            self._share_context = context
        self._last_framebuffer_size = self._framebuffer_dimensions()
        thread = MpvRenderThread(
            self,
            self._engine,
            self._share_context,
            self.requestedFormat(),
        )
        self._render_thread = thread
        thread.set_framebuffer_size(*self._last_framebuffer_size)
        thread.set_exposed(self.isExposed())
        thread.rendererReady.connect(self._thread_renderer_ready, Qt.ConnectionType.QueuedConnection)
        thread.rendererError.connect(self._thread_renderer_error, Qt.ConnectionType.QueuedConnection)
        thread.rendererStopped.connect(
            self._thread_renderer_stopped,
            Qt.ConnectionType.QueuedConnection,
        )
        self._engine.signals.render_update.connect(
            thread.request_frame,
            Qt.ConnectionType.DirectConnection,
        )
        thread.start()
        return True

    @pyqtSlot()
    def _thread_renderer_ready(self) -> None:
        thread = self.sender()
        if thread is not self._render_thread or self._shutting_down:
            return
        self._renderer_active = True
        self._renderer_generation += 1
        self.rendererReady.emit()

    @pyqtSlot(str)
    def _thread_renderer_error(self, message: str) -> None:
        if self.sender() is self._render_thread:
            self.rendererError.emit(f"OpenGL renderer could not start: {message}")

    @pyqtSlot()
    def _thread_renderer_stopped(self) -> None:
        thread = self.sender()
        if thread is not self._render_thread:
            return
        if self._engine is not None:
            try:
                self._engine.signals.render_update.disconnect(thread.request_frame)
            except (TypeError, RuntimeError):
                pass
        was_active = self._renderer_active
        self._render_thread = None
        self._renderer_active = False
        if was_active:
            self.rendererDestroyed.emit()

    def shutdown_renderer(self, permanent: bool = True) -> None:
        if permanent:
            self._shutting_down = True
        thread = self._render_thread
        was_running = bool(thread and thread.isRunning())
        if thread is not None:
            if self._engine is not None:
                try:
                    self._engine.signals.render_update.disconnect(thread.request_frame)
                except (TypeError, RuntimeError):
                    pass
            thread.shutdown()
            if not thread.wait(5000):
                self.logger.error("Timed out waiting for the mpv render thread to stop")
            self._render_thread = None
        if self._renderer_active or was_running:
            self._renderer_active = False
            self.rendererDestroyed.emit()
        if permanent:
            context = self._share_context
            self._share_context = None
            if context is not None:
                context.deleteLater()

    @pyqtSlot()
    def _context_about_to_be_destroyed(self) -> None:
        if self._share_context is not None:
            try:
                self.shutdown_renderer(permanent=False)
            finally:
                self._share_context = None

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
