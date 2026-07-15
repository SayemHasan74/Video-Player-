"""Windows SMTC integration with a raw media-key fallback."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal


class WindowsMediaController(QObject):
    """Publish Now Playing state and route system transport actions.

    `winsdk` is optional at runtime.  If WinRT cannot be initialized for the
    current desktop view, Qt media-key events remain active as the fallback.
    """

    actionRequested = pyqtSignal(str)

    BUTTON_ACTIONS = {
        "PLAY": "play",
        "PAUSE": "pause",
        "STOP": "stop",
        "NEXT": "next",
        "PREVIOUS": "previous",
    }

    def __init__(self, enabled: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.enabled = bool(enabled)
        self.available = False
        self._controls: Any | None = None
        self._button_token: Any | None = None
        self._media: Any | None = None
        self._proxy_player: Any | None = None
        self._uri_type: Any | None = None
        self._stream_reference_type: Any | None = None
        self._artwork_path: Path | None = None
        if self.enabled and os.name == "nt":
            self._initialize_smtc()

    def _initialize_smtc(self) -> None:
        try:
            from winsdk.windows import media
            from winsdk.windows.foundation import Uri
            from winsdk.windows.storage.streams import RandomAccessStreamReference

            try:
                controls = media.SystemMediaTransportControls.get_for_current_view()
            except Exception:
                # Qt desktop windows do not own a CoreWindow.  A silent WinRT
                # MediaPlayer provides the supported desktop SMTC bridge; it
                # never receives a source and libmpv remains the sole player.
                from winsdk.windows.media.playback import MediaPlayer

                self._proxy_player = MediaPlayer()
                controls = self._proxy_player.system_media_transport_controls
            controls.is_enabled = True
            controls.is_play_enabled = True
            controls.is_pause_enabled = True
            controls.is_stop_enabled = True
            controls.is_next_enabled = True
            controls.is_previous_enabled = True
            self._button_token = controls.add_button_pressed(self._button_pressed)
            self._controls = controls
            self._media = media
            self._uri_type = Uri
            self._stream_reference_type = RandomAccessStreamReference
            self.available = True
        except Exception as exc:
            self.logger.info("Windows SMTC unavailable; using raw media keys: %s", exc)

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        if not enabled:
            self.shutdown()
            self.enabled = False
            return
        self.enabled = True
        if os.name == "nt":
            self._initialize_smtc()

    def _button_pressed(self, _sender: object, args: object) -> None:
        name = str(getattr(getattr(args, "button", None), "name", "")).upper()
        action = self.BUTTON_ACTIONS.get(name)
        if action:
            self.actionRequested.emit(action)

    def update_metadata(self, info: dict[str, object]) -> None:
        if not self.available or self._controls is None or self._media is None:
            return
        try:
            updater = self._controls.display_updater
            updater.type = (
                self._media.MediaPlaybackType.VIDEO
                if info.get("has_video") else self._media.MediaPlaybackType.MUSIC
            )
            properties = updater.video_properties if info.get("has_video") else updater.music_properties
            properties.title = str(info.get("title") or Path(str(info.get("source") or "")).stem)
            if not info.get("has_video"):
                properties.artist = str(info.get("artist") or "")
                properties.album_title = str(info.get("album") or "")
            updater.update()
        except Exception as exc:
            self.logger.debug("SMTC metadata update ignored: %s", exc)

    def set_playback_status(self, paused: bool) -> None:
        if not self.available or self._controls is None or self._media is None:
            return
        try:
            self._controls.playback_status = (
                self._media.MediaPlaybackStatus.PAUSED
                if paused else self._media.MediaPlaybackStatus.PLAYING
            )
        except Exception as exc:
            self.logger.debug("SMTC playback-state update ignored: %s", exc)

    def update_artwork(self, data: bytes | None) -> None:
        if (
            not data or not self.available or self._controls is None
            or self._uri_type is None or self._stream_reference_type is None
        ):
            return
        try:
            suffix = ".png" if data.startswith(b"\x89PNG") else ".jpg"
            path = Path(tempfile.gettempdir()) / f"comet-v2-now-playing{suffix}"
            path.write_bytes(data)
            updater = self._controls.display_updater
            updater.thumbnail = self._stream_reference_type.create_from_uri(
                self._uri_type(path.as_uri())
            )
            updater.update()
            self._artwork_path = path
        except Exception as exc:
            self.logger.debug("SMTC artwork update ignored: %s", exc)

    def set_stopped(self) -> None:
        if not self.available or self._controls is None or self._media is None:
            return
        try:
            self._controls.playback_status = self._media.MediaPlaybackStatus.STOPPED
        except Exception:
            pass

    def shutdown(self) -> None:
        controls = self._controls
        if controls is not None and self._button_token is not None:
            try:
                controls.remove_button_pressed(self._button_token)
            except Exception:
                pass
        if controls is not None:
            try:
                controls.is_enabled = False
            except Exception:
                pass
        self.available = False
        self._button_token = None
        self._controls = None
        proxy = self._proxy_player
        if proxy is not None:
            try:
                proxy.close()
            except Exception:
                pass
        self._proxy_player = None
