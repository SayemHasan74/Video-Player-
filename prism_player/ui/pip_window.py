"""Independent Picture-in-Picture host for the shared video render surface."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QPoint, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QMouseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizeGrip, QVBoxLayout, QWidget


class PipWindow(QWidget):
    """Always-on-top window that temporarily owns the existing video widget."""

    restoreRequested = pyqtSignal()
    playPauseRequested = pyqtSignal()
    closePlayerRequested = pyqtSignal()

    def __init__(self, settings: Any) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.settings = settings
        self._video: QWidget | None = None
        self._shutting_down = False
        self._drag_origin: QPoint | None = None
        self._window_origin: QPoint | None = None
        self.setObjectName("pipWindow")
        self.setWindowTitle("Comet V2 — Picture in Picture")
        self.setMinimumSize(240, 140)
        self.resize(360, 210)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#pipWindow{background:#000;border:1px solid #34373d;}")

        self.video_host = QWidget(self)
        self.video_host.setStyleSheet("background:#000;")
        self.video_layout = QVBoxLayout(self.video_host)
        self.video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_layout.setSpacing(0)

        self.controls = QFrame(self)
        self.controls.setObjectName("pipControls")
        self.controls.setStyleSheet(
            "#pipControls{background:rgba(10,10,10,210);border-radius:7px;}"
            "QPushButton{background:transparent;color:#f4f4f4;border:0;padding:6px 10px;}"
            "QPushButton:hover{background:rgba(255,255,255,28);border-radius:5px;}"
        )
        self.play_button = QPushButton("Pause", self.controls)
        self.restore_button = QPushButton("Restore", self.controls)
        self.close_button = QPushButton("×", self.controls)
        controls_layout = QHBoxLayout(self.controls)
        controls_layout.setContentsMargins(5, 3, 5, 3)
        controls_layout.setSpacing(2)
        controls_layout.addWidget(self.play_button)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.restore_button)
        controls_layout.addWidget(self.close_button)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(self.grip.sizeHint())
        self.grip.setStyleSheet("background:transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.video_host)
        self.play_button.clicked.connect(self.playPauseRequested)
        self.restore_button.clicked.connect(self.restoreRequested)
        self.close_button.clicked.connect(self.closePlayerRequested)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(1400)
        self.hide_timer.timeout.connect(self._hide_overlays)
        self._hide_overlays()
        self.hide()

    @property
    def video_widget(self) -> QWidget | None:
        return self._video

    def attach_video(self, video: QWidget) -> None:
        if self._video is video:
            return
        if self._video is not None:
            self.video_layout.removeWidget(self._video)
        self._video = video
        # AA_ShareOpenGLContexts keeps a QOpenGLWidget's context alive while
        # it is re-parented between top-level windows.  Do not free libmpv's
        # render context here: Qt therefore has no reason to call
        # initializeGL() again, and the video would remain permanently black.
        # On platforms where Qt does replace the GL context, VideoWidget's
        # aboutToBeDestroyed handler performs the required teardown itself.
        video.hide()
        video.setParent(self.video_host)
        self.video_layout.addWidget(video)
        video.show()
        video.update()
        if hasattr(video, "ensure_renderer"):
            QTimer.singleShot(0, video.ensure_renderer)
        QTimer.singleShot(0, video.update)
        if hasattr(video, "mouseMoved"):
            video.mouseMoved.connect(self.reveal_controls)
        if hasattr(video, "dragStarted"):
            video.dragStarted.connect(self._start_video_drag)
            video.dragMoved.connect(self._move_video_drag)
            video.dragEnded.connect(self._end_video_drag)

    def detach_video(self, parent: QWidget) -> QWidget | None:
        video = self._video
        if video is None:
            return None
        try:
            if hasattr(video, "mouseMoved"):
                video.mouseMoved.disconnect(self.reveal_controls)
            if hasattr(video, "dragStarted"):
                video.dragStarted.disconnect(self._start_video_drag)
                video.dragMoved.disconnect(self._move_video_drag)
                video.dragEnded.disconnect(self._end_video_drag)
        except (TypeError, RuntimeError):
            pass
        self.video_layout.removeWidget(video)
        video.hide()
        video.setParent(parent)
        self._video = None
        if hasattr(video, "ensure_renderer"):
            QTimer.singleShot(0, video.ensure_renderer)
        QTimer.singleShot(0, video.update)
        return video

    def show_for_screen(self, screen: object | None) -> None:
        width = max(240, int(self.settings.get("pip.width", 360)))
        height = max(140, int(self.settings.get("pip.height", 210)))
        available = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        x = self.settings.get("pip.x")
        y = self.settings.get("pip.y")
        if x is None or y is None:
            x = available.right() - width - 18
            y = available.bottom() - height - 18
        x = min(max(int(x), available.left()), max(available.left(), available.right() - width + 1))
        y = min(max(int(y), available.top()), max(available.top(), available.bottom() - height + 1))
        self.setGeometry(x, y, min(width, available.width()), min(height, available.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.reveal_controls()

    def save_geometry(self) -> None:
        geometry = self.geometry()
        self.settings.set("pip.x", geometry.x())
        self.settings.set("pip.y", geometry.y())
        self.settings.set("pip.width", geometry.width())
        self.settings.set("pip.height", geometry.height())

    def set_paused(self, paused: bool) -> None:
        self.play_button.setText("Play" if paused else "Pause")

    def reveal_controls(self) -> None:
        if not self.isVisible():
            return
        self.controls.show()
        self.grip.show()
        self.controls.raise_()
        self.grip.raise_()
        self.hide_timer.start()

    def _hide_overlays(self) -> None:
        self.controls.hide()
        self.grip.hide()

    def _start_video_drag(self, global_pos: QPoint) -> None:
        self._drag_origin = QPoint(global_pos)
        self._window_origin = self.frameGeometry().topLeft()

    def _move_video_drag(self, global_pos: QPoint) -> None:
        if self._drag_origin is not None and self._window_origin is not None:
            self.move(self._window_origin + global_pos - self._drag_origin)

    def _end_video_drag(self) -> None:
        self._drag_origin = None
        self._window_origin = None

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        width = min(max(190, self.width() - 24), 330)
        self.controls.setGeometry((self.width() - width) // 2, self.height() - 48, width, 38)
        self.grip.move(self.width() - self.grip.width(), self.height() - self.grip.height())

    def enterEvent(self, event: QEvent) -> None:
        self.reveal_controls()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.hide_timer.start(350)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._window_origin = self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and self._window_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(self._window_origin + event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        self._window_origin = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutting_down:
            event.accept()
            return
        event.ignore()
        self.closePlayerRequested.emit()

    def shutdown(self, owner: QWidget | None = None) -> None:
        self._shutting_down = True
        self.hide_timer.stop()
        self.hide()
        if owner is not None:
            # Adopt the former top-level for deterministic destruction with
            # the main window. Closing two independent top-level widgets from
            # inside MainWindow.closeEvent can corrupt Qt's native teardown.
            self.setParent(owner, Qt.WindowType.Widget)
