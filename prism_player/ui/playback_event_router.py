"""Central signal routing between the player session and active Qt views."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject

from utils.time_utils import format_time


class PlaybackEventRouter(QObject):
    """Own player/view signal lifecycles instead of scattering them in MainWindow."""

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self._connections: list[tuple[Any, Callable[..., Any]]] = []

    def connect_all(self) -> None:
        window = self.window
        control = window.control_bar
        player = window.player
        self._connect(control.seekPreviewRequested, self.preview_seek_from_ui)
        self._connect(control.seekRequested, self.seek_from_ui)
        self._connect(control.volumeChanged, self.volume_from_ui)
        self._connect(control.speedChanged, self.speed_from_ui)
        self._connect(player.timeChanged, self.time_changed)
        self._connect(player.durationChanged, self.duration_changed)
        self._connect(player.pauseStateChanged, control.set_paused)
        self._connect(player.pauseStateChanged, window.music_mode.view.set_paused)
        self._connect(player.pauseStateChanged, window.pip_window.set_paused)
        self._connect(player.pauseStateChanged, window.media_controls.set_playback_status)
        self._connect(player.pauseStateChanged, self.playback_state_changed)
        self._connect(player.volumeChanged, control.set_volume_state)
        self._connect(player.volumeChanged, window.music_mode.view.set_volume_state)
        self._connect(player.speedChanged, control.set_speed)
        self._connect(player.tracksChanged, self.tracks_changed)
        self._connect(player.chaptersChanged, window.playlist_panel.set_chapters)
        self._connect(player.chaptersChanged, window.control_bar.set_chapters)
        self._connect(player.bufferingChanged, window.buffering_indicator.set_active)
        self._connect(player.bufferRangesChanged, window.control_bar.set_buffered_ranges)
        self._connect(player.fileEnded, window._play_next)
        self._connect(player.gaplessAdvanced, window._gapless_advanced)
        self._connect(player.stopped, window.media_controls.set_stopped)
        self._connect(player.error, self.player_error)
        self._connect(player.stateChanged, window.playlist_panel.quick_settings.set_state)
        self._connect(player.loaded, window.music_mode.source_loaded)
        self._connect(player.mediaInfoChanged, window._media_info_changed)

    def shutdown(self) -> None:
        for signal, slot in reversed(self._connections):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._connections.clear()

    def preview_seek_from_ui(self, seconds: float) -> None:
        """Publish immediate feedback and use a cheap keyframe scrub seek."""
        window = self.window
        window.player.seek_preview(seconds)
        self._publish_seek_position(seconds)
        window.osd.show_message(
            f"Seek: {format_time(seconds)} / {format_time(window.session.duration)}",
            category="seek",
        )

    def seek_from_ui(self, seconds: float) -> None:
        window = self.window
        window.actions.trigger("seek_ui", seconds)
        self._publish_seek_position(seconds)
        window.osd.show_message(
            f"Seek: {format_time(seconds)} / {format_time(window.session.duration)}",
            category="seek",
        )
        window._note_user_activity()

    def _publish_seek_position(self, seconds: float) -> None:
        window = self.window
        target = max(0.0, min(float(seconds), window.session.duration or float(seconds)))
        window.session.update_position(target)
        window.control_bar.set_time(target, window.session.duration)
        window.music_mode.view.set_time(target, window.session.duration)

    def volume_from_ui(self, volume: int) -> None:
        window = self.window
        window.actions.trigger("set_volume", volume)
        window.osd.show_message(f"Volume: {int(volume)}%", category="volume")
        window._note_user_activity()

    def speed_from_ui(self, speed: float) -> None:
        window = self.window
        window.actions.trigger("set_speed", speed)
        window.osd.show_message(f"Speed: {float(speed):g}×", category="speed")
        window._note_user_activity()

    def time_changed(self, seconds: float) -> None:
        window = self.window
        window.session.update_position(seconds)
        window.control_bar.set_time(window.session.position, window.session.duration)
        window.music_mode.view.set_time(window.session.position, window.session.duration)
        window.playlist_panel.update_current_chapter(window.session.position)
        current = window.playlist.current_item()
        if current:
            window.playlist_panel.update_progress(
                current.source, window.session.position, window.session.duration
            )
        window.plugins.events.emit(
            "playback.time", {"position": seconds, "duration": window.session.duration}
        )

    def duration_changed(self, seconds: float) -> None:
        window = self.window
        window.session.update_duration(seconds)
        window.control_bar.set_time(window.session.position, window.session.duration)
        window.music_mode.view.set_time(window.session.position, window.session.duration)
        current = window.playlist.current_item()
        if current and not current.is_url and seconds > 0 and window.settings.get("thumbnails.enabled", True):
            window._start_thumbnails(current.source, seconds)
        window.plugins.events.emit("playback.duration", seconds)

    def tracks_changed(self, audio: list, subtitles: list) -> None:
        window = self.window
        window.audio_tracks = audio
        window.subtitle_tracks = subtitles
        window.playlist_panel.quick_settings.set_tracks(audio, subtitles)
        window.plugins.events.emit("playback.tracks", {"audio": audio, "subtitles": subtitles})

    def playback_state_changed(self, paused: bool) -> None:
        window = self.window
        window._is_playing = not paused
        window.osd.show_message("Paused" if paused else "Playing", category="playback")
        window._show_player_chrome()
        if paused or window._mini_mode:
            window.overlays.hide_timer.stop()
        else:
            window._schedule_hide_player_chrome(3000)
        window.plugins.events.emit("playback.pause", paused)

    def player_error(self, text: str) -> None:
        self.window.osd.show_message(text, "error")

    def _connect(self, signal: Any, slot: Callable[..., Any]) -> None:
        signal.connect(slot)
        self._connections.append((signal, slot))
