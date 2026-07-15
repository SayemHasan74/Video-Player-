"""Application settings, constants, and JSON persistence for Comet Player."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_NAME = "Comet V2"
APP_SHORT_NAME = "Comet V2"
APP_VERSION = "2.0.0-dev"

DEFAULT_WINDOW_SIZE = (1100, 680)
MIN_WINDOW_SIZE = (285, 120)
TITLE_BAR_HEIGHT = 40
CONTROL_BAR_HEIGHT = 68
PLAYLIST_PANEL_WIDTH = 280
PIP_DEFAULT_SIZE = (360, 210)
PIP_MINIMUM_SIZE = (240, 140)

SPEED_STEPS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0)

MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".3g2",
        ".3gp",
        ".aac",
        ".ac3",
        ".aiff",
        ".ape",
        ".asf",
        ".avi",
        ".dff",
        ".dsd",
        ".dsf",
        ".flac",
        ".flv",
        ".m2ts",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".opus",
        ".ts",
        ".wav",
        ".webm",
        ".wmv",
        ".wma",
    }
)
SUBTITLE_EXTENSIONS: frozenset[str] = frozenset({".ass", ".srt", ".ssa", ".sub", ".vtt"})


def app_data_dir() -> Path:
    """Return the per-user settings directory."""
    root = Path.home() / "AppData" / "Roaming" if (Path.home() / "AppData").exists() else Path.home()
    path = root / "CometV2"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_settings() -> dict[str, Any]:
    """Return default settings."""
    return deepcopy(
        {
            "window": {
                "width": DEFAULT_WINDOW_SIZE[0],
                "height": DEFAULT_WINDOW_SIZE[1],
                "x": None,
                "y": None,
                "maximized": False,
                "always_on_top": False,
                "screen_name": "",
                "screen_offset_x": None,
                "screen_offset_y": None,
                "drag_from_video": False,
                "minimize_to_pip_video": False,
            },
            "playback": {
                "volume": 80,
                "muted": False,
                "speed": 1.0,
                "remember_position": True,
                "cover_mode": False,
                "open_behavior": "replace",
                "open_single_behavior": "replace",
                "open_multiple_behavior": "replace",
                "auto_resize": True,
                "auto_music_mode": True,
                "audio_only_override": False,
            },
            "paths": {
                "screenshot_dir": str(Path.home() / "Desktop"),
                "last_open_dir": str(Path.home()),
            },
            "ui": {
                "hide_controls_while_playing": True,
                "osc_position": "floating",
                "osc_hide_delay_ms": 3000,
                "osc_always_visible": False,
                "osc_scroll_enabled": True,
                "video_scroll_enabled": True,
                "osc_floating_offset": 0,
                "osc_toolbar": ["playlist", "subtitle", "audio", "screenshot", "ab_loop", "pip", "music", "cover", "fullscreen"],
                "sidebar_side": "right",
                "sidebar_width": 320,
                "quick_settings_width": 320,
                "sidebar_tab": "playlist",
                "playlist_pinned": False,
                "quick_settings_pinned": False,
                "show_playlist": False,
                "show_osd": True,
                "osd_position": "top",
                "osd_suppressed_categories": "",
                "buffering_throbber": "spinner",
                "animations": True,
                "theme": "dark",
            },
            "music_mode": {
                "show_playlist": False,
                "show_album_art": True,
            },
            "playlist": {
                "repeat_one": False,
                "repeat_all": False,
                "shuffle": False,
            },
            "video": {
                "hwdec": "auto-safe",
                "hwdec_fallback": True,
                "aspect": "auto",
                "rotation": 0,
                "lock_resize_aspect": True,
                "color_space": "srgb",
                "hdr_mode": "auto",
                "tone_mapping": "auto",
                "gamut_mapping": "auto",
                "hdr_peak_detection": "auto",
                "icc_profile": "",
            },
            "pip": {"x": None, "y": None, "width": 360, "height": 210},
            "audio": {
                "device": "auto",
                "gapless": "weak",
                "replaygain": "no",
                "replaygain_preamp": 0.0,
                "replaygain_clip": False,
                "replaygain_fallback": 0.0,
                "languages": "",
                "media_keys": True,
                "dsd_decode": "pcm",
            },
            "subtitle": {
                "autoload": True, "encoding": "auto", "font": "Segoe UI",
                "size": 42, "color": "#ffffff", "outline": 2, "position": 100,
                "exclude_embedded_auto": False,
            },
            "network": {
                "preferred_format": "bestvideo+bestaudio/best",
                "proxy": "",
                "user_agent": "",
            },
            "thumbnails": {"enabled": True, "samples": 100, "cache_mb": 512},
            "startup": {
                "show_welcome": True,
                "reopen_last": False,
                "last_source": "",
                "show_playlist_recents": False,
                "playlist_recents": [],
            },
            "advanced": {"mpv_options": ""},
            "keys": {"profile": "Default"},
        }
    )


class SettingsStore:
    """Small JSON-backed settings store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "settings.json"
        self.data = default_settings()

    def load(self) -> dict[str, Any]:
        """Load persisted settings, recovering corrupted JSON."""
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = self._merge(default_settings(), raw)
                # Migrate the original single opening preference without
                # changing an existing user's behavior.  New installs can
                # configure single and multiple selections independently.
                raw_playback = raw.get("playback", {}) if isinstance(raw, dict) else {}
                if isinstance(raw_playback, dict) and "open_behavior" in raw_playback:
                    previous = str(raw_playback.get("open_behavior", "replace"))
                    if "open_single_behavior" not in raw_playback:
                        self.set("playback.open_single_behavior", previous)
                    if "open_multiple_behavior" not in raw_playback:
                        self.set("playback.open_multiple_behavior", previous)
                gapless = self.get("audio.gapless", "weak")
                if isinstance(gapless, bool):
                    self.set("audio.gapless", "yes" if gapless else "no")
            else:
                self.save()
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logging.getLogger(__name__).warning("Resetting corrupted settings: %s", exc)
            self.data = default_settings()
            self.save()
        return self.data

    def save(self) -> None:
        """Write settings to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, dotted_key: str, fallback: Any = None) -> Any:
        """Read a nested setting by dotted key."""
        current: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return fallback
            current = current[part]
        return current

    def set(self, dotted_key: str, value: Any) -> None:
        """Set a nested setting by dotted key."""
        current = self.data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    def _merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = self._merge(base[key], value)
            else:
                base[key] = value
        return base


def global_stylesheet() -> str:
    """Return the app-wide Qt stylesheet."""
    return """
QWidget { background: #0d0d0d; color: #f0f0f0;
          font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif; font-size: 13px; }
QToolTip { background: #1a1a1a; color: #f0f0f0; border: 1px solid #3a3a3a;
           border-radius: 6px; padding: 4px 8px; }
QPushButton { background: transparent; border: none; color: #f0f0f0;
              border-radius: 8px; outline: none; padding: 4px 10px; }
QPushButton:hover { background: rgba(255,255,255,34); }
QPushButton:pressed { background: rgba(255,255,255,22); }
QPushButton:disabled { color: #505050; }
QMenu { background: #1a1a1a; border: 1px solid #303030; border-radius: 8px; padding: 4px 0; }
QMenu::item { padding: 7px 20px 7px 12px; }
QMenu::item:selected { background: #2a2a2a; border-radius: 4px; }
QMenu::separator { height: 1px; background: #2e2e2e; margin: 4px 0; }
QDialog { background: #111111; }
QLineEdit { background: #1a1a1a; border: 1px solid #303030; border-radius: 6px;
            padding: 6px 10px; color: #f0f0f0; }
QLineEdit:focus { border-color: #eeeeee; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;
                       border: 1.5px solid #404040; background: transparent; }
QCheckBox::indicator:checked { background: #eeeeee; border-color: #eeeeee; }
QSlider { outline: none; }
QSlider::groove:horizontal { height: 4px; background: #2e2e2e; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #eeeeee; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0;
                              border-radius: 7px; background: white; }
"""
