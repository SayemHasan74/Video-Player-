"""python-mpv wrapper used by the Comet Player UI."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, Qt, pyqtSignal, pyqtSlot

from core.dll_bootstrap import vendored_mpv_path
from core.mpv_engine import MpvEngine
from core.mpv_properties import (
    AF,
    AID,
    ALANG,
    AUDIO_DELAY,
    AUDIO_DEVICE,
    AUDIO_DEVICE_LIST,
    AVSYNC,
    BRIGHTNESS,
    CMD_AUDIO_FILTER,
    CMD_LOADFILE,
    CMD_SCREENSHOT_TO_FILE,
    CMD_SEEK,
    CMD_STOP,
    CMD_SUB_ADD,
    CMD_VIDEO_FILTER,
    CHAPTER_LIST,
    CONTAINER_FPS,
    CONTRAST,
    DEMUXER_CACHE_DURATION,
    DEMUXER_CACHE_STATE,
    DISPLAY_FPS,
    DURATION,
    EOF_REACHED,
    FRAME_DROP_COUNT,
    GAMMA,
    GAMUT_MAPPING_MODE,
    GAPLESS_AUDIO,
    HDR_COMPUTE_PEAK,
    HEIGHT,
    HTTP_PROXY,
    HUE,
    HWDEC,
    HWDEC_CURRENT,
    ICC_PROFILE,
    METADATA,
    MUTE,
    PATH,
    PAUSE,
    PAUSED_FOR_CACHE,
    CACHE_BUFFERING_STATE,
    REPLAYGAIN,
    REPLAYGAIN_CLIP,
    REPLAYGAIN_FALLBACK,
    REPLAYGAIN_PREAMP,
    SATURATION,
    SECONDARY_SID,
    SECONDARY_SUB_DELAY,
    SECONDARY_SUB_VISIBILITY,
    SEEKING,
    SID,
    SPEED,
    SUB_BORDER_SIZE,
    SUB_CODEPAGE,
    SUB_COLOR,
    SUB_DELAY,
    SUB_FONT,
    SUB_FONT_SIZE,
    SUB_POS,
    SUB_SHADOW_OFFSET,
    SUB_VISIBILITY,
    TARGET_PRIM,
    TARGET_TRC,
    TIME_POS,
    TONE_MAPPING,
    TRACK_LIST,
    USER_AGENT,
    VF,
    VIDEO_ASPECT_OVERRIDE,
    VIDEO_PARAMS,
    VIDEO_ROTATE,
    VID,
    VOLUME,
    WIDTH,
)
from core.video_pipeline import VideoPipelineConfig
from utils.languages import normalize_language_code, normalize_language_preferences


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
    bufferingStateChanged = pyqtSignal(bool, int)
    bufferRangesChanged = pyqtSignal(list)
    fileEnded = pyqtSignal()
    gaplessAdvanced = pyqtSignal(str)
    stopped = pyqtSignal()
    loaded = pyqtSignal(str)
    error = pyqtSignal(str)
    rendererReady = pyqtSignal()
    stateChanged = pyqtSignal(dict)
    filtersChanged = pyqtSignal(list, list)
    mediaInfoChanged = pyqtSignal(dict)

    @property
    def state(self):
        """Expose the one authoritative PlayerState cache to controllers."""
        return self.mpv.state if isinstance(getattr(self, "mpv", None), MpvEngine) else None

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def _position(self) -> float:
        state = self.state
        return float(state.position) if state is not None else float(self.__dict__.get("_compat_position", 0.0))

    @_position.setter
    def _position(self, value: float) -> None:
        state = self.state
        if state is not None:
            state.set_local(TIME_POS, float(value))
        else:
            self.__dict__["_compat_position"] = float(value)

    @property
    def _duration(self) -> float:
        state = self.state
        return float(state.duration) if state is not None else float(self.__dict__.get("_compat_duration", 0.0))

    @_duration.setter
    def _duration(self, value: float) -> None:
        state = self.state
        if state is not None:
            state.set_local(DURATION, float(value))
        else:
            self.__dict__["_compat_duration"] = float(value)

    @property
    def _paused(self) -> bool:
        state = self.state
        return bool(state.paused) if state is not None else bool(self.__dict__.get("_compat_paused", True))

    @_paused.setter
    def _paused(self, value: bool) -> None:
        state = self.state
        if state is not None:
            state.set_local(PAUSE, bool(value))
        else:
            self.__dict__["_compat_paused"] = bool(value)

    @property
    def _volume(self) -> int:
        state = self.state
        fallback = int(self.__dict__.get("_compat_volume", 80))
        return int(state.get(VOLUME, fallback)) if state is not None else fallback

    @_volume.setter
    def _volume(self, value: int) -> None:
        state = self.state
        if state is not None:
            state.set_local(VOLUME, int(value))
        else:
            self.__dict__["_compat_volume"] = int(value)

    @property
    def _muted(self) -> bool:
        state = self.state
        fallback = bool(self.__dict__.get("_compat_muted", False))
        return bool(state.get(MUTE, fallback)) if state is not None else fallback

    @_muted.setter
    def _muted(self, value: bool) -> None:
        state = self.state
        if state is not None:
            state.set_local(MUTE, bool(value))
        else:
            self.__dict__["_compat_muted"] = bool(value)

    @property
    def _speed(self) -> float:
        state = self.state
        fallback = float(self.__dict__.get("_compat_speed", 1.0))
        return float(state.get(SPEED, fallback)) if state is not None else fallback

    @_speed.setter
    def _speed(self, value: float) -> None:
        state = self.state
        if state is not None:
            state.set_local(SPEED, float(value))
        else:
            self.__dict__["_compat_speed"] = float(value)

    def __init__(
        self,
        video_widget: QObject | None = None,
        parent: QObject | None = None,
        settings: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self.mpv: Any | None = None
        self.is_loaded = False
        self.current_source = ""
        self._duration = 0.0
        self._position = 0.0
        self._paused = True
        # PlayerState receives the same queued mpv callbacks before this
        # facade, so its cached value may already equal the callback payload.
        # Track UI publication independently from the authoritative cache.
        self._last_emitted_position = 0.0
        self._last_emitted_duration = 0.0
        self._last_emitted_pause = True
        self._pause_command_deadline = 0.0
        self._volume = int(settings.get("playback.volume", 80)) if settings is not None else 80
        self._muted = bool(settings.get("playback.muted", False)) if settings is not None else False
        self._speed = float(settings.get("playback.speed", 1.0)) if settings is not None else 1.0
        self._ended_emitted = False
        self._buffering = False
        self._buffering_percent = 0
        self._buffer_ranges: tuple[tuple[float, float], ...] = ()
        self._last_track_signature: tuple = ()
        self._last_state: dict[str, Any] = {}
        self._last_filter_signature: tuple = ()
        self._last_media_info_signature: tuple = ()
        self._gapless_mode = "no"
        self._queued_gapless_source = ""
        self._gapless_transition_source = ""
        self._last_preview_seek: float | None = None
        self._exclude_embedded_subtitle_auto = False
        self._video_pipeline = VideoPipelineConfig.from_settings(settings) if settings is not None else VideoPipelineConfig()
        self._video_widget = video_widget
        self._load_mpv()
        self._wire_mpv_signals()
        if video_widget is not None and hasattr(video_widget, "set_backend"):
            video_widget.rendererReady.connect(self.rendererReady)
            video_widget.rendererError.connect(self.error)
            video_widget.set_backend(self)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)

    @staticmethod
    def mpv_dll_exists(base_dir: Path) -> bool:
        """Return True only for the deliberately vendored DLL."""
        del base_dir
        return vendored_mpv_path().is_file()

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
            self._last_emitted_position = 0.0
            self._last_emitted_duration = 0.0
            self.timeChanged.emit(0.0)
            self.durationChanged.emit(0.0)
            self._buffer_ranges = ()
            self.bufferRangesChanged.emit([])
            self._buffering = False
            self._buffering_percent = 0
            self.bufferingStateChanged.emit(False, 0)
            self.stopped.emit()
            self._queued_gapless_source = ""
            self._gapless_transition_source = ""
            self.mpv.command(CMD_LOADFILE, source, "replace")
            if self._exclude_embedded_subtitle_auto:
                # Apply immediately after the file-local track state exists;
                # explicitly loaded external tracks can still select themselves.
                self.mpv.sid = "no"
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
        self._last_emitted_pause = paused
        self._pause_command_deadline = time.monotonic() + 0.5
        self.pauseStateChanged.emit(paused)

    def stop(self) -> None:
        """Stop playback."""
        if self.mpv is None:
            return
        try:
            self.mpv.command(CMD_STOP)
        finally:
            self.is_loaded = False
            self.current_source = ""
            self._position = 0.0
            self._last_emitted_position = 0.0
            self._ended_emitted = False
            self.timeChanged.emit(0.0)
            self._buffer_ranges = ()
            self.bufferRangesChanged.emit([])
            self._buffering = False
            self._buffering_percent = 0
            self.bufferingStateChanged.emit(False, 0)

    def seek_relative(self, delta: float) -> None:
        """Seek relative seconds."""
        if self.is_loaded and self.mpv is not None:
            self._last_preview_seek = None
            self.mpv.command(CMD_SEEK, delta, "relative")

    def seek_preview(self, seconds: float) -> None:
        """Jump quickly to a nearby keyframe while the user is scrubbing."""
        if self.is_loaded and self.mpv is not None:
            target = max(0.0, float(seconds))
            self._last_preview_seek = target
            self.mpv.command(CMD_SEEK, target, "absolute+keyframes")

    def complete_ui_seek(self, seconds: float) -> None:
        """Finish scrubbing without a second decoder stall during playback.

        Active playback keeps the already-issued keyframe seek.  An already
        paused player can afford one precise landing because it cannot create
        a new visible playback interruption.
        """
        if not self.is_loaded or self.mpv is None:
            return
        target = max(0.0, float(seconds))
        preview_matches = (
            self._last_preview_seek is not None
            and abs(self._last_preview_seek - target) < 0.0001
        )
        self._last_preview_seek = None
        if self._paused:
            self.seek_absolute(target)
        elif not preview_matches:
            self.seek_preview(target)
            self._last_preview_seek = None

    def seek_absolute(self, seconds: float) -> None:
        """Seek to absolute seconds."""
        if self.is_loaded and self.mpv is not None:
            self._last_preview_seek = None
            self.mpv.command(CMD_SEEK, max(0.0, float(seconds)), "absolute+exact")

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

    def set_loglevel(self, level: str) -> str:
        """Apply the Preferences → Advanced mpv verbosity setting."""
        resolved = level if level in {"warn", "info", "debug", "trace"} else "warn"
        if isinstance(self.mpv, MpvEngine):
            self.mpv.set_loglevel(resolved)
        return resolved

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

    def configure_subtitles(self, *, exclude_embedded_auto: bool = False) -> None:
        """Configure selection policy without removing embedded tracks from the UI."""
        self._exclude_embedded_subtitle_auto = bool(exclude_embedded_auto)

    def set_property(self, name: str, value: Any) -> bool:
        """Set an arbitrary live mpv property from reactive settings panels."""
        if self.mpv is not None:
            try:
                if isinstance(self.mpv, MpvEngine):
                    self.mpv.set_property(name, value)
                elif isinstance(getattr(self.mpv, "properties", None), dict):
                    self.mpv.properties[name] = value
                else:
                    setattr(self.mpv, name.replace("-", "_"), value)
                self._last_state[name] = value
                self.stateChanged.emit(dict(self._last_state))
                return True
            except Exception as exc:
                self.logger.warning("Could not set mpv property %s: %s", name, exc)
                self.error.emit(f"Setting unavailable: {name}")
        return False

    def set_audio_delay(self, seconds: float) -> bool:
        """Apply signed A/V delay without truthiness or unsigned coercion."""
        return self.set_property(AUDIO_DELAY, max(-100.0, min(100.0, float(seconds))))

    def audio_devices(self) -> list[dict[str, str]]:
        """Return mpv's discovered device IDs with human-readable labels."""
        raw = self.get_property(AUDIO_DEVICE_LIST, []) or []
        devices: list[dict[str, str]] = [{"name": "auto", "description": "System default"}]
        seen = {"auto"}
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in seen:
                continue
            devices.append({"name": name, "description": str(entry.get("description") or name)})
            seen.add(name)
        return devices

    def set_audio_device(self, name: str) -> str:
        """Select a real mpv device ID, safely falling back to the default."""
        requested = str(name or "auto").strip() or "auto"
        known = {entry["name"] for entry in self.audio_devices()}
        applied = requested if requested == "auto" or requested in known else "auto"
        if applied != requested:
            self.error.emit("The selected audio device is unavailable; using the system default")
        self.set_property(AUDIO_DEVICE, applied)
        return applied

    def configure_audio(
        self,
        *,
        replaygain: str = "no",
        replaygain_preamp: float = 0.0,
        replaygain_clip: bool = False,
        replaygain_fallback: float = 0.0,
        gapless: str | bool = "weak",
        languages: object = "",
        device: str = "auto",
    ) -> None:
        """Apply normalization, gapless, language, and device preferences."""
        replaygain = replaygain if replaygain in {"no", "track", "album"} else "no"
        if isinstance(gapless, bool):
            gapless_mode = "yes" if gapless else "no"
        else:
            gapless_mode = str(gapless)
        if gapless_mode not in {"no", "weak", "yes"}:
            gapless_mode = "weak"
        properties = {
            REPLAYGAIN: replaygain,
            REPLAYGAIN_PREAMP: max(-15.0, min(15.0, float(replaygain_preamp))),
            REPLAYGAIN_CLIP: "yes" if replaygain_clip else "no",
            REPLAYGAIN_FALLBACK: max(-15.0, min(15.0, float(replaygain_fallback))),
        }
        normalized_languages = normalize_language_preferences(languages)
        if normalized_languages:
            properties[ALANG] = normalized_languages
        for name, value in properties.items():
            self.set_property(name, value)
        self.set_gapless_mode(gapless_mode)
        self.set_audio_device(device)

    def set_gapless_mode(self, mode: str | bool) -> str:
        if isinstance(mode, bool):
            normalized = "yes" if mode else "no"
        else:
            normalized = str(mode)
        if normalized not in {"no", "weak", "yes"}:
            normalized = "weak"
        self._gapless_mode = normalized
        self.set_property(GAPLESS_AUDIO, normalized)
        return normalized

    def configure_video_pipeline(self, config: VideoPipelineConfig) -> VideoPipelineConfig:
        """Apply validated color output and fall back to software decoding."""
        self._video_pipeline = config.validated()
        for name, value in self._video_pipeline.mpv_properties().items():
            if name == HWDEC:
                continue
            self.set_property(name, value)
        self.set_hwdec(self._video_pipeline.hwdec)
        return self._video_pipeline

    def set_hwdec(self, method: str | None) -> str:
        """Apply the prompt's resolved Windows hwdec branch."""
        if self.mpv is None:
            return "no"
        try:
            if isinstance(self.mpv, MpvEngine):
                return self.mpv.set_hwdec(method)
            resolved = "no" if not method or method == "no" else ("d3d11va" if method == "d3d11va" else "auto")
            if not self.set_property(HWDEC, resolved):
                raise RuntimeError("hardware decoder property rejected")
            return resolved
        except Exception as exc:
            self.logger.warning("Could not set hardware decoding: %s", exc)
            if self._video_pipeline.hwdec_fallback:
                self.set_property(HWDEC, "no")
            return "no"

    @staticmethod
    def _source_key(source: str) -> str:
        if "://" in source:
            return source.casefold()
        try:
            return str(Path(source).resolve()).casefold()
        except (OSError, ValueError):
            return source.casefold()

    @classmethod
    def sources_equal(cls, first: str, second: str) -> bool:
        return cls._source_key(first) == cls._source_key(second)

    def queue_gapless(self, source: str) -> bool:
        """Append one local audio successor to mpv's internal playlist."""
        if self.mpv is None or not self.is_loaded or self._gapless_mode == "no" or not source:
            return False
        if self._source_key(source) == self._source_key(self.current_source):
            return False
        try:
            self.mpv.command(CMD_LOADFILE, source, "append")
            self._queued_gapless_source = source
            return True
        except Exception as exc:
            self._queued_gapless_source = ""
            self.logger.debug("Could not queue gapless successor: %s", exc)
            return False

    def consume_gapless_transition(self, source: str) -> bool:
        if self._source_key(source) != self._source_key(self._gapless_transition_source):
            return False
        self._gapless_transition_source = ""
        return True

    def get_property(self, name: str, fallback: Any = None) -> Any:
        if self.mpv is None:
            return fallback
        try:
            if isinstance(self.mpv, MpvEngine):
                value = self.mpv.get_property(name, fallback)
            elif name == TRACK_LIST:
                value = getattr(self.mpv, "track_list", fallback)
            elif name == CHAPTER_LIST:
                value = getattr(self.mpv, "chapter_list", fallback)
            elif isinstance(getattr(self.mpv, "properties", None), dict):
                value = self.mpv.properties.get(name, fallback)
            else:
                value = getattr(self.mpv, name.replace("-", "_"), fallback)
            return fallback if value is None else value
        except Exception:
            return fallback

    def add_filter(self, kind: str, value: str) -> None:
        if self.mpv is not None:
            try:
                self.mpv.command(CMD_VIDEO_FILTER if kind == "video" else CMD_AUDIO_FILTER, "add", value)
                self._emit_filters()
            except Exception as exc:
                self.error.emit(f"Filter failed: {exc}")

    def remove_filter(self, kind: str, value: str) -> None:
        if self.mpv is not None:
            try:
                self.mpv.command(CMD_VIDEO_FILTER if kind == "video" else CMD_AUDIO_FILTER, "remove", value)
                self._emit_filters()
            except Exception as exc:
                self.error.emit(f"Could not remove filter: {exc}")

    def replace_filter(self, kind: str, label: str, value: str | None) -> None:
        """Replace one application-owned labelled filter without touching user filters."""
        if self.mpv is None:
            return
        command = CMD_VIDEO_FILTER if kind == "video" else CMD_AUDIO_FILTER
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
                primary_before = self.get_property(SID, "no")
                track_id = self.mpv.command(CMD_SUB_ADD, str(path), "auto" if secondary or not select else "select")
                if track_id in (None, False, "no"):
                    resolved = str(path.resolve())
                    matches = [
                        track.get("id") for track in (getattr(self.mpv, "track_list", None) or [])
                        if track.get("type") == "sub" and str(track.get("external-filename") or "") == resolved
                    ]
                    track_id = max((track for track in matches if isinstance(track, int)), default=None)
                if secondary and track_id not in (None, "no"):
                    self.mpv.secondary_sid = track_id
                    if primary_before not in (None, "auto"):
                        self.mpv.sid = primary_before
                elif select and track_id not in (None, "no"):
                    # Do not rely solely on sub-add's select mode: explicitly
                    # assign the returned id so external tracks cannot be added
                    # successfully yet remain inactive.
                    self.mpv.sid = track_id
                return track_id
            except Exception as exc:
                self.error.emit(f"Subtitle failed: {exc}")
        return None

    def screenshot(self, output: Path) -> bool:
        """Save a video screenshot."""
        if self.mpv is None or not self.is_loaded:
            return False
        try:
            self.mpv.command(CMD_SCREENSHOT_TO_FILE, str(output), "video")
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
                    self.mpv.command(CMD_STOP)
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
        """Create the sole mpv owner after the entry point imported python-mpv."""
        try:
            self.mpv = MpvEngine(settings=self.settings, parent=self)
        except Exception as exc:
            self.logger.warning("mpv engine initialization failed: %s", exc)
            self.mpv = None
            return
        self.mpv.volume = self._volume
        self.mpv.mute = self._muted
        self.mpv.speed = self._speed
        self.mpv.pause = True
        self.mpv.panscan = 0.0

    def _wire_mpv_signals(self) -> None:
        if not isinstance(self.mpv, MpvEngine):
            return
        queued = Qt.ConnectionType.QueuedConnection
        self.mpv.signals.position_changed.connect(self._on_position_changed, queued)
        self.mpv.signals.duration_changed.connect(self._on_duration_changed, queued)
        self.mpv.signals.pause_changed.connect(self._on_pause_changed, queued)
        self.mpv.signals.file_loaded.connect(self._on_file_loaded, queued)
        self.mpv.signals.property_changed.connect(self._on_property_changed, queued)
        self.mpv.signals.mpv_shutdown.connect(self._on_mpv_shutdown, queued)
        self.mpv.signals.log_message.connect(self._on_mpv_log, queued)

    @pyqtSlot(float)
    def _on_position_changed(self, position: float) -> None:
        position = float(position)
        self._position = position
        if abs(position - self._last_emitted_position) > 0.01:
            self._last_emitted_position = position
            self.timeChanged.emit(position)

    @pyqtSlot(float)
    def _on_duration_changed(self, duration: float) -> None:
        duration = float(duration)
        self._duration = duration
        if abs(duration - self._last_emitted_duration) > 0.01:
            self._last_emitted_duration = duration
            self.durationChanged.emit(duration)

    @pyqtSlot(bool)
    def _on_pause_changed(self, paused: bool) -> None:
        if time.monotonic() < self._pause_command_deadline:
            paused = self._paused
        paused = bool(paused)
        self._paused = paused
        if paused != self._last_emitted_pause:
            self._last_emitted_pause = paused
            self.pauseStateChanged.emit(paused)

    @pyqtSlot()
    def _on_file_loaded(self) -> None:
        self._emit_tracks()
        self._emit_chapters()
        self._emit_media_info()

    @pyqtSlot(str, object)
    def _on_property_changed(self, _name: str, _value: object) -> None:
        self._poll_state()

    @pyqtSlot()
    def _on_mpv_shutdown(self) -> None:
        self.is_loaded = False

    @pyqtSlot(str, str)
    def _on_mpv_log(self, level: str, message: str) -> None:
        target = self.logger.warning if level in {"warn", "error", "fatal"} else self.logger.debug
        target("mpv %s: %s", level, message)

    def _poll_state(self) -> None:
        """Refresh derived UI state from the main-thread PlayerState cache."""
        if self.mpv is None:
            return
        try:
            position = float(self.get_property(TIME_POS, self._position) or 0.0)
            duration = float(self.get_property(DURATION, self._duration) or 0.0)
            paused = bool(self.get_property(PAUSE, self._paused))
            if time.monotonic() < self._pause_command_deadline:
                paused = self._paused
            paused_for_cache = bool(self.get_property(PAUSED_FOR_CACHE, False))
            seeking = bool(self.get_property(SEEKING, False))
            buffering = self.is_loaded and paused_for_cache and not seeking
            try:
                buffering_percent = max(
                    0,
                    min(100, round(float(self.get_property(CACHE_BUFFERING_STATE, 0) or 0))),
                )
            except (TypeError, ValueError):
                buffering_percent = 0
            buffering_changed = buffering != self._buffering
            percent_changed = buffering_percent != self._buffering_percent
            if buffering_changed:
                self._buffering = buffering; self.bufferingChanged.emit(buffering)
            self._buffering_percent = buffering_percent
            if buffering_changed or percent_changed:
                self.bufferingStateChanged.emit(buffering, buffering_percent)
            cache_state = self.get_property(DEMUXER_CACHE_STATE, {}) or {}
            raw_ranges = cache_state.get("seekable-ranges", []) if isinstance(cache_state, dict) else []
            ranges: list[tuple[float, float]] = []
            for item in raw_ranges:
                if not isinstance(item, dict):
                    continue
                start = float(item.get("start", 0) or 0)
                end = float(item.get("end", 0) or 0)
                if end > start:
                    ranges.append((start, end))
            signature = tuple((round(start, 2), round(end, 2)) for start, end in ranges)
            if signature != self._buffer_ranges:
                self._buffer_ranges = signature
                self.bufferRangesChanged.emit(list(signature))
            if abs(position - self._last_emitted_position) > 0.1:
                self._position = position
                self._last_emitted_position = position
                self.timeChanged.emit(position)
            if abs(duration - self._last_emitted_duration) > 0.1:
                self._duration = duration
                self._last_emitted_duration = duration
                self.durationChanged.emit(duration)
            if paused != self._last_emitted_pause:
                self._paused = paused
                self._last_emitted_pause = paused
                self.pauseStateChanged.emit(paused)
            actual_source = str(self.get_property(PATH, "") or "")
            if (
                actual_source
                and self._queued_gapless_source
                and self._source_key(actual_source) == self._source_key(self._queued_gapless_source)
                and self._source_key(actual_source) != self._source_key(self.current_source)
            ):
                self.current_source = self._queued_gapless_source
                self._gapless_transition_source = self._queued_gapless_source
                self._queued_gapless_source = ""
                self._ended_emitted = False
                self.loaded.emit(self.current_source)
                self.gaplessAdvanced.emit(self.current_source)
            self._emit_tracks()
            self._emit_media_info()
            self._emit_reactive_state()
            self._emit_filters()
            reached_eof = bool(self.get_property(EOF_REACHED, False))
            if self.is_loaded and reached_eof and not self._ended_emitted:
                self._ended_emitted = True
                self.fileEnded.emit()
        except Exception as exc:
            self.logger.debug("mpv poll ignored: %s", exc)

    def _emit_tracks(self) -> None:
        """Emit current audio/subtitle tracks."""
        track_list = self.get_property(TRACK_LIST, []) or []
        audio_tracks = []
        subtitle_tracks = []
        for track in track_list:
            target = audio_tracks if track.get("type") == "audio" else subtitle_tracks if track.get("type") == "sub" else None
            if target is not None:
                normalized = dict(track)
                normalized["lang"] = normalize_language_code(track.get("lang"))
                target.append(normalized)
        signature = tuple(
            (track.get("type"), track.get("id"), track.get("lang"), track.get("title"), track.get("selected"))
            for track in track_list
        )
        if signature != self._last_track_signature:
            self._last_track_signature = signature
            self.tracksChanged.emit(audio_tracks, subtitle_tracks)

    def _emit_media_info(self) -> None:
        """Publish stream-kind and tag metadata for reactive player layouts."""
        track_list = self.get_property(TRACK_LIST, []) or []
        video_tracks = [track for track in track_list if track.get("type") == "video"]
        audio_tracks = [track for track in track_list if track.get("type") == "audio"]
        has_album_art = any(bool(track.get("albumart") or track.get("image")) for track in video_tracks)
        has_video = any(not bool(track.get("albumart") or track.get("image")) for track in video_tracks)
        video_track = next(
            (track for track in video_tracks if not bool(track.get("albumart") or track.get("image"))),
            {},
        )
        video_params = self.get_property(VIDEO_PARAMS, {}) or {}
        if not isinstance(video_params, dict):
            video_params = {}
        video_width = int(
            self.get_property(WIDTH, 0)
            or video_track.get("demux-w") or video_track.get("w") or video_params.get("w") or 0
        )
        video_height = int(
            self.get_property(HEIGHT, 0)
            or video_track.get("demux-h") or video_track.get("h") or video_params.get("h") or 0
        )
        album_art_id = next(
            (
                track.get("id")
                for track in video_tracks
                if track.get("albumart") or track.get("image")
            ),
            None,
        )
        raw_metadata = self.get_property(METADATA, {}) or {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        metadata = {str(key).casefold(): value for key, value in raw_metadata.items()}
        selected_audio = next((track for track in audio_tracks if track.get("selected")), audio_tracks[0] if audio_tracks else {})
        audio_codec = str(selected_audio.get("codec") or selected_audio.get("codec-desc") or "")
        source_suffix = Path(self.current_source).suffix.casefold() if "://" not in self.current_source else ""
        transfer = str(video_params.get("gamma") or "")
        primaries = str(video_params.get("primaries") or "")
        info = {
            "source": self.current_source,
            "has_audio": bool(audio_tracks),
            "has_video": has_video,
            "has_album_art": has_album_art,
            "video_width": video_width,
            "video_height": video_height,
            "video_aspect": float(video_params.get("aspect") or (video_width / video_height if video_height else 0.0)),
            # These stay in the same mpv instance across PiP re-parenting;
            # publishing them makes preservation an explicit, testable state.
            "color_primaries": primaries,
            "color_transfer": transfer,
            "color_matrix": str(video_params.get("colormatrix") or ""),
            "is_hdr": transfer.casefold() in {"pq", "st2084", "hlg"},
            "is_wide_gamut": primaries.casefold() in {"bt.2020", "display-p3", "dci-p3"},
            "output_color_space": self._video_pipeline.color_space,
            "hdr_mode": self._video_pipeline.hdr_mode,
            "hwdec_current": str(self.get_property(HWDEC_CURRENT, "") or ""),
            "audio_codec": audio_codec,
            "audio_language": normalize_language_code(selected_audio.get("lang")),
            "is_dsd": source_suffix in {".dsd", ".dsf", ".dff"} or "dsd" in audio_codec.casefold(),
            "album_art_id": album_art_id,
            "title": str(metadata.get("title") or ""),
            "artist": str(metadata.get("artist") or ""),
            "album": str(metadata.get("album") or ""),
        }
        signature = tuple(info.items())
        if signature != self._last_media_info_signature:
            self._last_media_info_signature = signature
            self.mediaInfoChanged.emit(info)

    def _emit_reactive_state(self) -> None:
        properties = (
            AID, SID, SECONDARY_SID, SPEED, VOLUME, HWDEC,
            VIDEO_ASPECT_OVERRIDE, VIDEO_ROTATE, BRIGHTNESS, CONTRAST,
            SATURATION, GAMMA, HUE, AUDIO_DELAY, SUB_DELAY,
            SECONDARY_SUB_DELAY, SUB_VISIBILITY, SECONDARY_SUB_VISIBILITY,
            SUB_FONT, SUB_FONT_SIZE, SUB_COLOR, SUB_BORDER_SIZE,
            SUB_SHADOW_OFFSET, SUB_POS, SUB_CODEPAGE,
            REPLAYGAIN, REPLAYGAIN_PREAMP, REPLAYGAIN_CLIP,
            GAPLESS_AUDIO, AUDIO_DEVICE, ALANG,
            TARGET_PRIM, TARGET_TRC, TONE_MAPPING, GAMUT_MAPPING_MODE,
        )
        state = {name: self.get_property(name) for name in properties}
        state = {name: value for name, value in state.items() if value is not None}
        if state != self._last_state:
            self._last_state = state
            self.stateChanged.emit(dict(state))

    def _emit_filters(self) -> None:
        video = self.get_property(VF, []) or []
        audio = self.get_property(AF, []) or []
        signature = (repr(video), repr(audio))
        if signature != self._last_filter_signature:
            self._last_filter_signature = signature
            self.filtersChanged.emit(list(video), list(audio))

    def _emit_chapters(self) -> None:
        if self.mpv is None: return
        try: self.chaptersChanged.emit(self.get_property(CHAPTER_LIST, []) or [])
        except Exception: self.chaptersChanged.emit([])
