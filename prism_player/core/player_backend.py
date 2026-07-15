"""python-mpv wrapper used by the Comet Player UI."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

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
        self._pause_command_deadline = 0.0
        self._volume = int(settings.get("playback.volume", 80)) if settings is not None else 80
        self._muted = bool(settings.get("playback.muted", False)) if settings is not None else False
        self._speed = float(settings.get("playback.speed", 1.0)) if settings is not None else 1.0
        self._ended_emitted = False
        self._buffering = False
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
            self._buffer_ranges = ()
            self.bufferRangesChanged.emit([])
            self.stopped.emit()
            self._queued_gapless_source = ""
            self._gapless_transition_source = ""
            self.mpv.command("loadfile", source, "replace")
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
            self._buffer_ranges = ()
            self.bufferRangesChanged.emit([])

    def seek_relative(self, delta: float) -> None:
        """Seek relative seconds."""
        if self.is_loaded and self.mpv is not None:
            self._last_preview_seek = None
            self.mpv.command("seek", delta, "relative")

    def seek_preview(self, seconds: float) -> None:
        """Jump quickly to a nearby keyframe while the user is scrubbing."""
        if self.is_loaded and self.mpv is not None:
            target = max(0.0, float(seconds))
            self._last_preview_seek = target
            self.mpv.command("seek", target, "absolute+keyframes")

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

    def configure_subtitles(self, *, exclude_embedded_auto: bool = False) -> None:
        """Configure selection policy without removing embedded tracks from the UI."""
        self._exclude_embedded_subtitle_auto = bool(exclude_embedded_auto)

    def set_property(self, name: str, value: Any) -> bool:
        """Set an arbitrary live mpv property from reactive settings panels."""
        if self.mpv is not None:
            try:
                self.mpv._set_property(name, value)
                self._last_state[name] = value
                self.stateChanged.emit(dict(self._last_state))
                return True
            except Exception as exc:
                self.logger.warning("Could not set mpv property %s: %s", name, exc)
                self.error.emit(f"Setting unavailable: {name}")
        return False

    def set_audio_delay(self, seconds: float) -> bool:
        """Apply signed A/V delay without truthiness or unsigned coercion."""
        return self.set_property("audio-delay", max(-100.0, min(100.0, float(seconds))))

    def audio_devices(self) -> list[dict[str, str]]:
        """Return mpv's discovered device IDs with human-readable labels."""
        raw = self.get_property("audio-device-list", []) or []
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
        self.set_property("audio-device", applied)
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
            "replaygain": replaygain,
            "replaygain-preamp": max(-15.0, min(15.0, float(replaygain_preamp))),
            "replaygain-clip": "yes" if replaygain_clip else "no",
            "replaygain-fallback": max(-15.0, min(15.0, float(replaygain_fallback))),
        }
        normalized_languages = normalize_language_preferences(languages)
        if normalized_languages:
            properties["alang"] = normalized_languages
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
        self.set_property("gapless-audio", normalized)
        return normalized

    def configure_video_pipeline(self, config: VideoPipelineConfig) -> VideoPipelineConfig:
        """Apply validated color output and fall back to software decoding."""
        self._video_pipeline = config.validated()
        for name, value in self._video_pipeline.mpv_properties().items():
            if name == "hwdec":
                continue
            self.set_property(name, value)
        if not self.set_property("hwdec", self._video_pipeline.hwdec) and self._video_pipeline.hwdec_fallback:
            self.set_property("hwdec", "no")
        return self._video_pipeline

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
            self.mpv.command("loadfile", source, "append")
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
                primary_before = self.get_property("sid", "no")
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
        """Import python-mpv after the entry-point bootstrap and create it."""
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
            # Music Mode decodes tag bytes itself.  This avoids libmpv/ffmpeg
            # failures on common APIC tags whose MIME label is wrong.
            "audio_display": "no",
            "audio_fallback_to_null": True,
            "keep_open": True,
            "sub_auto": "no",
            "ytdl": False,
            "hwdec": self._video_pipeline.hwdec,
            "vo": "libmpv",
            "demuxer_max_bytes": "512MiB",
            "demuxer_max_back_bytes": "128MiB",
            "vd_lavc_threads": 0,
            # Exact seeks may still decode from the previous keyframe, but
            # dropping intermediate frames makes the final landing much faster.
            "hr_seek_framedrop": True,
            "log_handler": self._mpv_log,
        }
        profile_modes = [self._video_pipeline.hwdec]
        if self._video_pipeline.hwdec_fallback:
            profile_modes.extend(["auto-safe", "no"])
        profiles = tuple({"hwdec": mode} for index, mode in enumerate(profile_modes) if mode not in profile_modes[:index])
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
        self.mpv.mute = self._muted
        self.mpv.speed = self._speed
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
            paused_for_cache = bool(self.get_property("paused-for-cache", getattr(self.mpv, "paused_for_cache", False)))
            seeking = bool(self.get_property("seeking", False))
            buffering = self.is_loaded and paused_for_cache and not seeking
            if buffering != self._buffering:
                self._buffering = buffering; self.bufferingChanged.emit(buffering)
            cache_state = self.get_property("demuxer-cache-state", {}) or {}
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
            if abs(position - self._position) > 0.1:
                self._position = position
                self.timeChanged.emit(position)
            if abs(duration - self._duration) > 0.1:
                self._duration = duration
                self.durationChanged.emit(duration)
            if paused != self._paused:
                self._paused = paused
                self.pauseStateChanged.emit(paused)
            actual_source = str(self.get_property("path", "") or "")
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
            reached_eof = bool(self.get_property("eof-reached", False))
            if self.is_loaded and reached_eof and not self._ended_emitted:
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
        track_list = getattr(self.mpv, "track_list", None) or []
        video_tracks = [track for track in track_list if track.get("type") == "video"]
        audio_tracks = [track for track in track_list if track.get("type") == "audio"]
        has_album_art = any(bool(track.get("albumart") or track.get("image")) for track in video_tracks)
        has_video = any(not bool(track.get("albumart") or track.get("image")) for track in video_tracks)
        video_track = next(
            (track for track in video_tracks if not bool(track.get("albumart") or track.get("image"))),
            {},
        )
        video_params = self.get_property("video-params", {}) or {}
        if not isinstance(video_params, dict):
            video_params = {}
        video_width = int(
            self.get_property("width", 0)
            or video_track.get("demux-w") or video_track.get("w") or video_params.get("w") or 0
        )
        video_height = int(
            self.get_property("height", 0)
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
        raw_metadata = self.get_property("metadata", {}) or {}
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
            "hwdec_current": str(self.get_property("hwdec-current", "") or ""),
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
            "aid", "sid", "secondary-sid", "speed", "volume", "hwdec",
            "video-aspect-override", "video-rotate", "brightness", "contrast",
            "saturation", "gamma", "hue", "audio-delay", "sub-delay",
            "secondary-sub-delay", "sub-visibility", "secondary-sub-visibility",
            "sub-font", "sub-font-size", "sub-color", "sub-border-size",
            "sub-shadow-offset", "sub-pos", "sub-codepage",
            "replaygain", "replaygain-preamp", "replaygain-clip",
            "gapless-audio", "audio-device", "alang",
            "target-prim", "target-trc", "tone-mapping", "gamut-mapping-mode",
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
