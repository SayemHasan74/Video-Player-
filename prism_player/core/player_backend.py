"""python-mpv wrapper used by the Prism Player UI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

_DLL_DIRECTORY_HANDLES = []


class PlayerBackend(QObject):
    """Control mpv playback and expose Qt signals for UI synchronization."""

    timeChanged = pyqtSignal(float)
    durationChanged = pyqtSignal(float)
    pauseStateChanged = pyqtSignal(bool)
    volumeChanged = pyqtSignal(int, bool)
    speedChanged = pyqtSignal(float)
    tracksChanged = pyqtSignal(list, list)
    fileEnded = pyqtSignal()
    loaded = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_widget: QObject | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.mpv: Any | None = None
        self.is_loaded = False
        self.current_source = ""
        self._duration = 0.0
        self._position = 0.0
        self._paused = True
        self._volume = 80
        self._muted = False
        self._speed = 1.0
        self._ended_emitted = False
        self._load_mpv(video_widget)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self._poll_state)
        self.poll_timer.start()

    @staticmethod
    def mpv_dll_exists(base_dir: Path) -> bool:
        """Return True if mpv is beside the app or available to Windows loader."""
        candidates = [base_dir, base_dir.parent, *[Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]]
        return any((directory / "mpv-2.dll").exists() or (directory / "libmpv-2.dll").exists() for directory in candidates)

    def load(self, source: str, start_position: float = 0.0) -> None:
        """Load a file path or URL into mpv."""
        if self.mpv is None:
            self.error.emit("mpv is not available.")
            return
        try:
            self.current_source = source
            self._ended_emitted = False
            self.mpv.command("loadfile", source, "replace")
            if start_position > 1:
                QTimer.singleShot(500, lambda: self.seek_absolute(start_position))
            self.is_loaded = True
            self.loaded.emit(source)
            QTimer.singleShot(120, lambda: self.set_paused(False))
        except Exception as exc:
            self.logger.exception("Could not load media")
            self.error.emit(f"Could not open file: {exc}")

    def play_pause(self) -> None:
        """Toggle play/pause."""
        if self.is_loaded:
            self.set_paused(not self._paused)

    def set_paused(self, paused: bool) -> None:
        """Set pause state."""
        if not self.is_loaded or self.mpv is None:
            return
        self.mpv.pause = paused
        self._paused = paused
        self.pauseStateChanged.emit(paused)

    def stop(self) -> None:
        """Stop playback."""
        if self.mpv is None:
            return
        try:
            self.mpv.command("stop")
        finally:
            self.is_loaded = False
            self.current_source = ""
            self._position = 0.0
            self._ended_emitted = False
            self.timeChanged.emit(0.0)

    def seek_relative(self, delta: float) -> None:
        """Seek relative seconds."""
        if self.is_loaded and self.mpv is not None:
            self.mpv.command("seek", delta, "relative")

    def seek_absolute(self, seconds: float) -> None:
        """Seek to absolute seconds."""
        if self.is_loaded and self.mpv is not None:
            self.mpv.command("seek", max(0.0, seconds), "absolute")

    def set_volume(self, volume: int) -> None:
        """Set volume."""
        if self.mpv is None:
            return
        self._volume = max(0, min(150, int(volume)))
        self.mpv.volume = self._volume
        self.volumeChanged.emit(self._volume, self._muted)

    def change_volume(self, delta: int) -> None:
        """Adjust volume."""
        self.set_volume(self._volume + delta)

    def set_muted(self, muted: bool) -> None:
        """Set mute state."""
        if self.mpv is None:
            return
        self._muted = muted
        self.mpv.mute = muted
        self.volumeChanged.emit(self._volume, self._muted)

    def toggle_mute(self) -> None:
        """Toggle mute."""
        self.set_muted(not self._muted)

    def set_speed(self, speed: float) -> None:
        """Set playback speed."""
        if self.mpv is None:
            return
        self._speed = float(speed)
        self.mpv.speed = self._speed
        self.speedChanged.emit(self._speed)

    def set_cover_mode(self, enabled: bool) -> None:
        """Crop video so fullscreen can cover the whole screen."""
        if self.mpv is not None:
            self.mpv.panscan = 1.0 if enabled else 0.0
            self.mpv.video_unscaled = False

    def set_subtitle_track(self, track_id: int | str) -> None:
        """Select subtitle track."""
        if self.mpv is not None:
            self.mpv.sid = track_id

    def set_audio_track(self, track_id: int | str) -> None:
        """Select audio track."""
        if self.mpv is not None:
            self.mpv.aid = track_id

    def load_subtitle(self, path: Path) -> None:
        """Load external subtitle."""
        if self.mpv is not None and self.is_loaded:
            self.mpv.command("sub-add", str(path), "select")

    def screenshot(self, output: Path) -> bool:
        """Save a video screenshot."""
        if self.mpv is None or not self.is_loaded:
            return False
        try:
            self.mpv.command("screenshot-to-file", str(output), "video")
            return True
        except Exception as exc:
            self.logger.warning("Screenshot failed: %s", exc)
            return False

    def set_ab_loop(self, start: float | None, end: float | None) -> None:
        """Set or clear A-B loop."""
        if self.mpv is None:
            return
        self.mpv.ab_loop_a = "no" if start is None else start
        self.mpv.ab_loop_b = "no" if end is None else end

    def shutdown(self) -> None:
        """Terminate mpv."""
        self.poll_timer.stop()
        if self.mpv is not None:
            try:
                self.mpv.terminate()
            except Exception as exc:
                self.logger.debug("mpv terminate ignored: %s", exc)

    def _load_mpv(self, video_widget: QObject | None) -> None:
        """Import python-mpv and create the player."""
        app_dir = Path(__file__).resolve().parents[1]
        root_dir = app_dir.parent
        os.environ["PATH"] = os.pathsep.join((str(app_dir), str(root_dir), os.environ.get("PATH", "")))
        for dll_dir in (app_dir, root_dir):
            if hasattr(os, "add_dll_directory") and dll_dir.exists():
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))
        try:
            from mpv import MPV
        except Exception as exc:
            self.logger.warning("python-mpv import failed: %s", exc)
            self.mpv = None
            return

        base_kwargs: dict[str, Any] = {
            "title": "Prism Player",
            "force_media_title": "Prism Player",
            "border": False,
            "force_window": False,
            "input_default_bindings": False,
            "input_vo_keyboard": False,
            "osc": False,
            "keep_open": True,
            "ytdl": False,
            "hwdec": "auto-safe",
            "demuxer_max_bytes": "512MiB",
            "demuxer_max_back_bytes": "128MiB",
            "vd_lavc_threads": 0,
            "log_handler": self._mpv_log,
        }
        if video_widget is not None:
            base_kwargs["wid"] = str(int(video_widget.winId()))

        profiles: tuple[dict[str, Any], ...] = (
            {"vo": "gpu-next", "gpu_api": "d3d11"},
            {"vo": "gpu", "gpu_api": "d3d11"},
            {},
            {"hwdec": "no"},
        )
        last_error: Exception | None = None
        for profile in profiles:
            try:
                self.mpv = MPV(**{**base_kwargs, **profile})
                break
            except Exception as exc:
                last_error = exc
                self.logger.warning("mpv startup profile failed: %s", exc)
        if self.mpv is None:
            self.logger.error("mpv could not start: %s", last_error)
            return
        self.mpv.volume = self._volume
        self.mpv.pause = True
        self.mpv.panscan = 0.0

    def _poll_state(self) -> None:
        """Poll mpv properties and emit changes."""
        if self.mpv is None:
            return
        try:
            position = float(self.mpv.time_pos or 0.0)
            duration = float(self.mpv.duration or 0.0)
            paused = bool(self.mpv.pause)
            if abs(position - self._position) > 0.1:
                self._position = position
                self.timeChanged.emit(position)
            if abs(duration - self._duration) > 0.1:
                self._duration = duration
                self.durationChanged.emit(duration)
            if paused != self._paused:
                self._paused = paused
                self.pauseStateChanged.emit(paused)
            self._emit_tracks()
            if self.is_loaded and duration > 0 and position >= duration - 0.4 and not paused and not self._ended_emitted:
                self._ended_emitted = True
                self.fileEnded.emit()
        except Exception as exc:
            self.logger.debug("mpv poll ignored: %s", exc)

    def _emit_tracks(self) -> None:
        """Emit current audio/subtitle tracks."""
        track_list = getattr(self.mpv, "track_list", None) or []
        audio_tracks = []
        subtitle_tracks = []
        for track in track_list:
            target = audio_tracks if track.get("type") == "audio" else subtitle_tracks if track.get("type") == "sub" else None
            if target is not None:
                target.append(track)
        self.tracksChanged.emit(audio_tracks, subtitle_tracks)

    def _mpv_log(self, level: str, prefix: str, text: str) -> None:
        """Forward mpv logs."""
        self.logger.debug("mpv %s %s: %s", level, prefix, text.rstrip())
