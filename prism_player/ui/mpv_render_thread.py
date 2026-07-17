# LOCKED BEHAVIOR — see Section 2.5. Do not move rendering back onto the GUI thread, and do not simplify the WM_NCHITTEST border logic, without flagging it first.
"""Dedicated, update-driven OpenGL presentation thread for libmpv."""

from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QSemaphore, QThread, pyqtSignal
from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat, QWindow

from core.mpv_engine import MpvEngine


class MpvRenderThread(QThread):
    """Own the only context allowed to render and swap the video surface."""

    rendererReady = pyqtSignal()
    rendererStopped = pyqtSignal()
    rendererError = pyqtSignal(str)

    def __init__(
        self,
        window: QWindow,
        engine: MpvEngine,
        share_context: QOpenGLContext,
        surface_format: QSurfaceFormat,
    ) -> None:
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self._window = window
        self._engine = engine
        self._share_context = share_context
        self._surface_format = surface_format
        self._wake = QSemaphore(0)
        self._state_lock = threading.Lock()
        self._frame_pending = False
        self._stop_requested = False
        self._exposed = False
        self._framebuffer_size = (1, 1)

    def request_frame(self) -> None:
        """Wake the render loop once; safe from mpv's callback thread."""
        with self._state_lock:
            if self._stop_requested or self._frame_pending:
                return
            self._frame_pending = True
        self._wake.release()

    def set_framebuffer_size(self, width: int, height: int) -> None:
        """Publish a physical-pixel size without performing any GL work."""
        with self._state_lock:
            self._framebuffer_size = (max(1, int(width)), max(1, int(height)))
        self.request_frame()

    def set_exposed(self, exposed: bool) -> None:
        with self._state_lock:
            self._exposed = bool(exposed)
        if exposed:
            self.request_frame()

    def shutdown(self) -> None:
        with self._state_lock:
            self._stop_requested = True
            self._frame_pending = True
        self._wake.release()

    def _snapshot(self) -> tuple[bool, bool, tuple[int, int]]:
        with self._state_lock:
            self._frame_pending = False
            return self._stop_requested, self._exposed, self._framebuffer_size

    @staticmethod
    def _get_proc_address(_opaque: object, name: bytes) -> int:
        context = QOpenGLContext.currentContext()
        if context is None:
            return 0
        address = context.getProcAddress(name)
        return int(address) if address else 0

    def run(self) -> None:
        """Block for mpv updates, then render and swap entirely off the GUI thread."""
        context = QOpenGLContext()
        context.setFormat(self._surface_format)
        context.setShareContext(self._share_context)
        renderer_created = False
        try:
            if not QOpenGLContext.supportsThreadedOpenGL():
                raise RuntimeError("The active Qt platform/driver does not support threaded OpenGL")
            if not context.create():
                raise RuntimeError("Render-thread OpenGL context creation failed")
            if not context.makeCurrent(self._window):
                raise RuntimeError("Render-thread OpenGL context could not be made current")
            try:
                self._engine.create_render_context(self._get_proc_address)
                renderer_created = True
            finally:
                context.doneCurrent()
            self.rendererReady.emit()
            self.request_frame()

            while True:
                self._wake.acquire()
                stop_requested, exposed, (width, height) = self._snapshot()
                if stop_requested:
                    break
                if not exposed:
                    continue
                if not context.makeCurrent(self._window):
                    self.logger.debug("Render-thread makeCurrent skipped while surface is unavailable")
                    continue
                try:
                    self._engine.render_frame(width, height)
                    context.swapBuffers(self._window)
                    self._engine.report_swap()
                finally:
                    context.doneCurrent()
        except Exception as exc:
            self.logger.exception("Dedicated mpv render thread failed")
            self.rendererError.emit(str(exc))
        finally:
            if renderer_created:
                made_current = context.makeCurrent(self._window)
                try:
                    self._engine.free_render_context()
                finally:
                    if made_current:
                        context.doneCurrent()
            self.rendererStopped.emit()
