"""Live quick-settings application and per-file visual state."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QRect


class MediaStateController(QObject):
    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def apply_quick_setting(self, key: str, value: object) -> None:
        window = self.window
        current = window.playlist.current_item()
        if key == "crop":
            if isinstance(value, dict) and value.get("w") and value.get("h"):
                crop = f"crop={value['w']}:{value['h']}:{value['x']}:{value['y']}"
                window.player.replace_filter("video", "comet_crop", crop)
            else:
                window.player.replace_filter("video", "comet_crop", None)
            if current is not None:
                window.media_states.update(current.source, crop=value)
            window.osd.show_message("Crop updated" if value else "Crop cleared", category="filters")
            return
        if key == "audio-eq":
            values = value if isinstance(value, dict) else {}
            filters = ",".join(
                f"equalizer=f={frequency}:width_type=o:width=1:g={gain}"
                for frequency, gain in values.items() if gain
            )
            window.player.replace_filter("audio", "comet_eq", f"lavfi=[{filters}]" if filters else None)
            return
        if key == "audio-delay":
            window.player.set_audio_delay(float(value))
            window.osd.show_message(f"Audio delay: {float(value):+.2f}s", category="tracks")
            return
        if key == "gapless-audio":
            window.player.set_gapless_mode(str(value))
            return
        if key == "video-rotate":
            value = int(value)
        if key == "video-aspect-override" and value == "auto":
            value = "no"
        window.player.set_property(key, value)
        if key in {"aid", "sid", "secondary-sid"}:
            label = "Audio" if key == "aid" else "Secondary subtitle" if key == "secondary-sid" else "Subtitle"
            window.osd.show_message(f"{label} track changed", category="tracks")
        if current is not None and key == "video-rotate":
            window.media_states.update(current.source, rotation=value)
        if current is not None and key == "video-aspect-override":
            window.media_states.update(current.source, aspect=value)
        if key == "video-rotate":
            window.osd.show_message(f"Rotation: {value}°", category="filters")
        elif key == "video-aspect-override":
            window.osd.show_message(f"Aspect: {'Auto' if value == 'no' else value}", category="filters")

    def apply_for_source(self, source: str) -> None:
        window = self.window
        current = window.playlist.current_item()
        if current is None or current.source != source:
            return
        state = window.media_states.get(source)
        default_aspect = window.settings.get("video.aspect", "auto")
        aspect = state.get("aspect", "no" if default_aspect == "auto" else default_aspect)
        rotation = int(state.get("rotation", window.settings.get("video.rotation", 0)) or 0)
        crop = state.get("crop")
        window.player.set_property("video-aspect-override", aspect)
        window.player.set_property("video-rotate", rotation)
        quick = window.playlist_panel.quick_settings
        if isinstance(crop, dict) and crop.get("w") and crop.get("h"):
            window.player.replace_filter(
                "video", "comet_crop",
                f"crop={crop['w']}:{crop['h']}:{crop.get('x', 0)}:{crop.get('y', 0)}",
            )
            quick.set_crop(crop["w"], crop["h"], crop.get("x", 0), crop.get("y", 0), emit=False)
        else:
            window.player.replace_filter("video", "comet_crop", None)
            quick.set_crop(0, 0, 0, 0, emit=False)

    def crop_selection_finished(self, selection: QRect) -> None:
        window = self.window
        params = window.player.get_property("video-params", {}) or {}
        source_width = int(params.get("w") or params.get("dw") or window.video.width())
        source_height = int(params.get("h") or params.get("dh") or window.video.height())
        if window.video.width() <= 0 or window.video.height() <= 0:
            return
        scale_x = source_width / window.video.width()
        scale_y = source_height / window.video.height()
        window.playlist_panel.quick_settings.set_crop(
            round(selection.width() * scale_x),
            round(selection.height() * scale_y),
            round(selection.x() * scale_x),
            round(selection.y() * scale_y),
        )
