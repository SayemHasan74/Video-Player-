"""Exclusive owner of python-mpv, its callbacks, and render context."""

from __future__ import annotations

import logging
import ctypes.util
from typing import Any, Callable

from PyQt6.QtCore import QObject

from core.dll_bootstrap import vendored_mpv_path
from core.mpv_properties import (
    CHAPTER_LIST,
    CMD_SEEK,
    CMD_STOP,
    DURATION,
    GPU_CONTEXT,
    HWDEC,
    OBSERVED_PROPERTIES,
    PAUSE,
    TIME_POS,
    TRACK_LIST,
    VOLUME,
    VO,
)
from core.mpv_signals import MpvSignals
from core.player_state import PlayerState


_MPV_MODULE: Any | None = None


def import_mpv_module() -> Any:
    """Import python-mpv only after QApplication and LC_NUMERIC=C exist."""
    global _MPV_MODULE
    if _MPV_MODULE is None:
        # python-mpv 1.0.7 insists on calling find_library() during import.
        # Resolve only its three libmpv probes to the already-loaded absolute
        # vendored DLL; never mutate or depend on PATH.
        original_find_library = ctypes.util.find_library

        def find_vendored_library(name: str) -> str | None:
            if name.casefold() in {"mpv-1.dll", "mpv-2.dll", "libmpv-2.dll"}:
                return str(vendored_mpv_path())
            return original_find_library(name)

        ctypes.util.find_library = find_vendored_library
        try:
            import mpv
        finally:
            ctypes.util.find_library = original_find_library

        _MPV_MODULE = mpv
    return _MPV_MODULE


class MpvEngine(QObject):
    """Own the live MPV object and expose main-thread-safe application methods."""

    def __init__(
        self,
        *,
        settings: Any | None = None,
        parent: QObject | None = None,
        title: str = "Comet Player",
    ) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.signals = MpvSignals(self)
        self.state = PlayerState(self.signals, self)
        self._mpv: Any | None = None
        self._render_context: Any | None = None
        self._proc_address_callback: Any | None = None
        self._property_callbacks: list[Callable[..., None]] = []
        self._observed_names: set[str] = set()
        self._event_callbacks: list[Callable[..., None]] = []
        self._title = title
        self._settings = settings
        self._create_player()

    @property
    def available(self) -> bool:
        return self._mpv is not None

    def _create_player(self) -> None:
        module = import_mpv_module()
        loglevel = "warn"
        if self._settings is not None:
            candidate = str(self._settings.get("advanced.mpv_loglevel", "warn"))
            if candidate in {"warn", "info", "debug", "trace"}:
                loglevel = candidate
        self._mpv = module.MPV(
            title=self._title,
            force_media_title=self._title,
            border=False,
            force_window=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            osc=False,
            vid="auto",
            hwdec="no",
            vo="libmpv",
            audio_display="no",
            audio_fallback_to_null=True,
            keep_open=True,
            keepaspect_window="no",
            sub_auto="no",
            ytdl=False,
            demuxer_max_bytes="512MiB",
            demuxer_max_back_bytes="128MiB",
            vd_lavc_threads=0,
            hr_seek_framedrop=True,
            loglevel=loglevel,
            log_handler=self._log_callback,
        )
        self._wire_observers()

    def _wire_observers(self) -> None:
        if self._mpv is None:
            return
        for property_name in OBSERVED_PROPERTIES:
            self.observe_property(property_name)

        module = import_mpv_module()

        def event_callback(event: object) -> None:
            event_id = event.event_id.value
            if event_id == module.MpvEventID.FILE_LOADED:
                self.signals.file_loaded.emit()
            elif event_id == module.MpvEventID.SHUTDOWN:
                self.signals.mpv_shutdown.emit()

        self._event_callbacks.append(event_callback)
        self._mpv.register_event_callback(event_callback)

    def _make_property_callback(self, property_name: str) -> Callable[[str, object], None]:
        if property_name == TIME_POS:
            def callback(_name: str, value: object) -> None:
                self.signals.position_changed.emit(float(value or 0.0))
        elif property_name == DURATION:
            def callback(_name: str, value: object) -> None:
                self.signals.duration_changed.emit(float(value or 0.0))
        elif property_name == PAUSE:
            def callback(_name: str, value: object) -> None:
                self.signals.pause_changed.emit(bool(value))
        else:
            def callback(name: str, value: object) -> None:
                self.signals.property_changed.emit(name, value)
        return callback

    def _log_callback(self, level: str, prefix: str, text: str) -> None:
        self.signals.log_message.emit(str(level), f"{prefix}: {text.rstrip()}")

    def command(self, name: str, *args: object) -> Any:
        if self._mpv is None:
            return None
        return self._mpv.command(name, *args)

    def get_property(self, name: str, fallback: Any = None) -> Any:
        if name not in self._observed_names:
            self.observe_property(name)
        return self.state.get(name, fallback)

    def observe_property(self, name: str) -> None:
        if self._mpv is None or name in self._observed_names:
            return
        callback = self._make_property_callback(name)
        self._property_callbacks.append(callback)
        self._observed_names.add(name)
        self._mpv.observe_property(name, callback)

    def set_property(self, name: str, value: Any) -> bool:
        if self._mpv is None:
            return False
        self._mpv._set_property(name, value)
        self.state.set_local(name, value)
        return True

    def set_loglevel(self, level: str) -> None:
        if self._mpv is not None:
            self._mpv.set_loglevel(level)

    def play(self) -> None:
        self.set_property(PAUSE, False)

    def pause(self) -> None:
        self.set_property(PAUSE, True)

    def seek(self, seconds: float, mode: str = "absolute+exact") -> None:
        self.command(CMD_SEEK, float(seconds), mode)

    def set_volume(self, value: int) -> None:
        self.set_property(VOLUME, int(value))

    def set_hwdec(self, method: str | None) -> str:
        resolved = "no" if not method or method == "no" else ("d3d11va" if method == "d3d11va" else "auto")
        if resolved == "d3d11va":
            self.set_property(VO, "gpu")
            self.set_property(GPU_CONTEXT, "d3d11")
        else:
            self.set_property(VO, "libmpv")
        self.set_property(HWDEC, resolved)
        return resolved

    def create_render_context(self, get_proc_address: Callable[[object, bytes], int]) -> None:
        if self._mpv is None or self._render_context is not None:
            return
        module = import_mpv_module()
        self._proc_address_callback = module.MpvGlGetProcAddressFn(get_proc_address)
        self._render_context = module.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": self._proc_address_callback},
        )
        self._render_context.update_cb = self._render_update_callback

    def _render_update_callback(self) -> None:
        self.signals.render_update.emit()

    def render_frame(self, width: int, height: int) -> None:
        if self._render_context is None:
            return
        self._render_context.render(
            opengl_fbo={"fbo": 0, "w": int(width), "h": int(height)},
            flip_y=True,
        )

    def report_swap(self) -> None:
        if self._render_context is not None:
            self._render_context.report_swap()

    def free_render_context(self) -> None:
        if self._render_context is None:
            return
        self._render_context.update_cb = None
        self._render_context.free()
        self._render_context = None
        self._proc_address_callback = None

    def terminate(self) -> None:
        if self._mpv is None:
            return
        self.free_render_context()
        self._mpv.terminate()
        self._mpv = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name == "track_list":
            return self.state.get(TRACK_LIST, [])
        if name == "chapter_list":
            return self.state.get(CHAPTER_LIST, [])
        property_name = name.replace("_", "-")
        return self.state.get(property_name)

    def __setattr__(self, name: str, value: Any) -> None:
        internal = name.startswith("_") or name in {"logger", "signals", "state"}
        if internal or "_mpv" not in self.__dict__ or self.__dict__.get("_mpv") is None:
            super().__setattr__(name, value)
            return
        self.set_property(name.replace("_", "-"), value)
