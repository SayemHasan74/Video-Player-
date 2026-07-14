"""python-mpv wrapper used by the Comet Player UI."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

_DLL_DIRECTORY_HANDLES = []


class PlayerBackend(QObject):
    """Control mpv playback and expose Qt signals for UI synchronization."""

    timeChanged = pyqtSignal(float)
    durationChanged = pyqtSignal(float)
    pauseStateChanged = pyqtSignal(bool)
    volumeChanged = pyqtSignal(int, bool)
    speedChanged = pyqtSignal(float)
    tracksChanged = pyqtSignal(list, list)
    chaptersChanged = pyqtSignal(list)
    bufferingChanged = pyqtSignal(bool)
    fileEnded = pyqtSignal()
    loaded = pyqtSignal(str)
    error = pyqtSignal(str)
    rendererReady = pyqtSignal()
    stateChanged = pyqtSignal(dict)
    filtersChanged = pyqtSignal(list, list)

    def __init__(self, video_widget: QObject | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.mpv: Any | None = None
        self.is_loaded = False
        self.current_source = ""
        self._duration = 0.0
        self._position = 0.0
        self._paused = True
        self._pause_command_deadline = 0.0
        self._volume = 80
        self._muted = False
        self._speed = 1.0
        self._ended_emitted = False
        self._buffering = False
        self._last_track_signature: tuple = ()
        self._last_state: dict[str, Any] = {}
        self._last_filter_signature: tuple = ()
        self._video_widget = video_widget
        self._load_mpv()
        if video_widget is not None and hasattr(video_widget, "set_backend"):
            video_widget.rendererReady.connect(self.rendererReady)
            video_widget.rendererError.connect(self.error)
            video_widget.set_backend(self)
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
            # A fresh file must publish its own timeline even when it happens
            # to have almost the same duration as the previous playlist item.
            # Keeping the old cached duration left the UI at 00:00 and made
            # the seek bar reject input because MainWindow had reset its copy.
            self._position = 0.0
            self._duration = 0.0
            self.timeChanged.emit(0.0)
            self.durationChanged.emit(0.0)
            self.mpv.command("loadfile", source, "replace")
            if start_position > 1:
                QTimer.singleShot(500, lambda: self.seek_absolute(start_position))
            self.is_loaded = True
            self.loaded.emit(source)
            QTimer.singleShot(120, lambda: self.set_paused(False))
            QTimer.singleShot(400, self._emit_chapters)
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
        self._pause_command_deadline = time.monotonic() + 0.5
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
            self.mpv.command("seek", max(0.0, float(seconds)), "absolute+exact")

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

    def set_secondary_subtitle_track(self, track_id: int | str) -> None:
        if self.mpv is not None:
            self.mpv.secondary_sid = track_id

    def set_property(self, name: str, value: Any) -> None:
        """Set an arbitrary live mpv property from reactive settings panels."""
        if self.mpv is not None:
            try:
                self.mpv._set_property(name, value)
                self._last_state[name] = value
                self.stateChanged.emit(dict(self._last_state))
            except Exception as exc:
                self.logger.warning("Could not set mpv property %s: %s", name, exc)
                self.error.emit(f"Setting unavailable: {name}")

    def get_property(self, name: str, fallback: Any = None) -> Any:
        if self.mpv is None:
            return fallback
        try:
            value = self.mpv._get_property(name)
            return fallback if value is None else value
        except Exception:
            return fallback

    def add_filter(self, kind: str, value: str) -> None:
        if self.mpv is not None:
            try:
                self.mpv.command("vf" if kind == "video" else "af", "add", value)
                self._emit_filters()
            except Exception as exc:
                self.error.emit(f"Filter failed: {exc}")

    def remove_filter(self, kind: str, value: str) -> None:
        if self.mpv is not None:
            try:
                self.mpv.command("vf" if kind == "video" else "af", "remove", value)
                self._emit_filters()
            except Exception as exc:
                self.error.emit(f"Could not remove filter: {exc}")

    def replace_filter(self, kind: str, label: str, value: str | None) -> None:
        """Replace one application-owned labelled filter without touching user filters."""
        if self.mpv is None:
            return
        command = "vf" if kind == "video" else "af"
        try:
            self.mpv.command(command, "remove", f"@{label}")
        except Exception:
            pass
        if value:
            try:
                self.mpv.command(command, "add", f"@{label}:{value}")
            except Exception as exc:
                self.error.emit(f"Filter failed: {exc}")
        self._emit_filters()

    def load_subtitle(self, path: Path, select: bool = True, secondary: bool = False) -> Any:
        """Load external subtitle."""
        if self.mpv is not None and self.is_loaded:
            try:
                track_id = self.mpv.command("sub-add", str(path), "auto" if secondary or not select else "select")
                if track_id in (None, False, "no"):
                    resolved = str(path.resolve())
                    matches = [
                        track.get("id") for track in (getattr(self.mpv, "track_list", None) or [])
                        if track.get("type") == "sub" and str(track.get("external-filename") or "") == resolved
                    ]
                    track_id = max((track for track in matches if isinstance(track, int)), default=None)
                if secondary and track_id not in (None, "no"):
                    self.mpv.secondary_sid = track_id
                return track_id
            except Exception as exc:
                self.error.emit(f"Subtitle failed: {exc}")
        return None

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
        """Stop playback, release GL resources, then terminate the mpv core."""
        self.poll_timer.stop()
        if self.mpv is not None:
            try:
                if self.is_loaded:
                    self.mpv.command("stop")
                    self._settle_shutdown(100)
                if self._video_widget is not None and hasattr(self._video_widget, "shutdown_renderer"):
                    self._video_widget.shutdown_renderer()
                    self._settle_shutdown(100)
                self.mpv.terminate()
            except Exception as exc:
                self.logger.debug("mpv terminate ignored: %s", exc)
            finally:
                self.mpv = None

    @staticmethod
    def _settle_shutdown(milliseconds: int) -> None:
        """Let native decoder/render threads finish without blocking Qt teardown."""
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def _load_mpv(self) -> None:
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
            "title": "Comet Player",
            "force_media_title": "Comet Player",
            "border": False,
            "force_window": False,
            "input_default_bindings": False,
            "input_vo_keyboard": False,
            "osc": False,
            "keep_open": True,
            "sub_auto": "no",
            "ytdl": False,
            "hwdec": "auto-safe",
            "vo": "libmpv",
            "demuxer_max_bytes": "512MiB",
            "demuxer_max_back_bytes": "128MiB",
            "vd_lavc_threads": 0,
            "log_handler": self._mpv_log,
        }
        profiles: tuple[dict[str, Any], ...] = (
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
            if time.monotonic() < self._pause_command_deadline:
                paused = self._paused
            buffering = bool(getattr(self.mpv, "paused_for_cache", False))
            if buffering != self._buffering:
                self._buffering = buffering; self.bufferingChanged.emit(buffering)
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
            self._emit_reactive_state()
            self._emit_filters()
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
        signature = tuple(
            (track.get("type"), track.get("id"), track.get("lang"), track.get("title"), track.get("selected"))
            for track in track_list
        )
        if signature != self._last_track_signature:
            self._last_track_signature = signature
            self.tracksChanged.emit(audio_tracks, subtitle_tracks)

    def _emit_reactive_state(self) -> None:
        properties = (
            "aid", "sid", "secondary-sid", "speed", "volume", "hwdec",
            "video-aspect-override", "video-rotate", "brightness", "contrast",
            "saturation", "gamma", "hue", "audio-delay", "sub-delay",
            "secondary-sub-delay", "sub-visibility", "secondary-sub-visibility",
            "sub-font", "sub-font-size", "sub-color", "sub-border-size",
            "sub-shadow-offset", "sub-pos", "sub-codepage",
        )
        state = {name: self.get_property(name) for name in properties}
        state = {name: value for name, value in state.items() if value is not None}
        if state != self._last_state:
            self._last_state = state
            self.stateChanged.emit(dict(state))

    def _emit_filters(self) -> None:
        video = self.get_property("vf", []) or []
        audio = self.get_property("af", []) or []
        signature = (repr(video), repr(audio))
        if signature != self._last_filter_signature:
            self._last_filter_signature = signature
            self.filtersChanged.emit(list(video), list(audio))

    def _emit_chapters(self) -> None:
        if self.mpv is None: return
        try: self.chaptersChanged.emit(getattr(self.mpv, "chapter_list", None) or [])
        except Exception: self.chaptersChanged.emit([])

    def _mpv_log(self, level: str, prefix: str, text: str) -> None:
        """Forward mpv logs."""
        self.logger.debug("mpv %s %s: %s", level, prefix, text.rstrip())
