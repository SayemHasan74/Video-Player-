"""QWidget host for the native mpv QWindow and ordinary Qt overlays."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from core.mpv_engine import MpvEngine
from ui.mpv_render_window import MpvRenderWindow


class _OffscreenRenderStub(QObject):
    """Non-native stand-in used only by Qt's headless test platform."""

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

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host
        self.renderer_active = False
        self.renderer_generation = 0
        self.framebuffer_size = (0, 0)

    def set_engine(self, _engine: MpvEngine | None) -> None:
        pass

    def ensure_renderer(self) -> bool:
        return False

    def shutdown_renderer(self, _permanent: bool = True) -> None:
        pass

    def devicePixelRatio(self) -> float:
        return self.host.devicePixelRatioF()


class VideoWidget(QWidget):
    """Overlay-safe host; the native render window remains internal plumbing."""

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Keep the QMainWindow/central-widget ancestor chain non-native. Only
        # the render container needs an HWND; otherwise a full-window native
        # ancestor intercepts WM_NCHITTEST before the top-level custom frame.
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setObjectName("videoSurfaceHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#videoSurfaceHost { background:#000000; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # Qt's offscreen test platform cannot safely create dozens of native
        # QWindows in one process. Windows production always creates the native
        # render window and embeds it through createWindowContainer().
        if QGuiApplication.platformName() == "offscreen":
            self.render_window = _OffscreenRenderStub(self)
            self.container = QWidget(self)
        else:
            self.render_window = MpvRenderWindow()
            self.container = QWidget.createWindowContainer(self.render_window, self)
            self.container.setAttribute(
                Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True
            )
        self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.container.setStyleSheet("background:#000000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.container)
        self._forward_signals()

    def _forward_signals(self) -> None:
        source = self.render_window
        source.doubleClicked.connect(self.doubleClicked)
        source.clicked.connect(self.clicked)
        source.rightClicked.connect(self.rightClicked)
        source.middleClicked.connect(self.middleClicked)
        source.scrolled.connect(self.scrolled)
        source.mouseMoved.connect(self.mouseMoved)
        source.mousePositionChanged.connect(self.mousePositionChanged)
        source.dragStarted.connect(self.dragStarted)
        source.dragMoved.connect(self.dragMoved)
        source.dragEnded.connect(self.dragEnded)
        source.keyPressed.connect(self.keyPressed)
        source.rendererReady.connect(self.rendererReady)
        source.rendererDestroyed.connect(self.rendererDestroyed)
        source.rendererError.connect(self.rendererError)

    @property
    def renderer_active(self) -> bool:
        return self.render_window.renderer_active

    @property
    def renderer_generation(self) -> int:
        return self.render_window.renderer_generation

    @property
    def framebuffer_size(self) -> tuple[int, int]:
        return self.render_window.framebuffer_size

    def _framebuffer_dimensions(self) -> tuple[int, int]:
        ratio = float(self.render_window.devicePixelRatio())
        return (
            max(1, round(self.width() * ratio)),
            max(1, round(self.height() * ratio)),
        )

    def set_backend(self, backend: Any) -> None:
        engine = getattr(backend, "mpv", None)
        self.render_window.set_engine(engine if isinstance(engine, MpvEngine) else None)

    def ensure_renderer(self) -> bool:
        return self.render_window.ensure_renderer()

    def shutdown_renderer(self, permanent: bool = True) -> None:
        self.render_window.shutdown_renderer(permanent)
