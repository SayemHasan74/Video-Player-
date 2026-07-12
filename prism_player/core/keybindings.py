"""Named, persistent keyboard-binding profiles."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from config.settings import app_data_dir


BUILTIN_PROFILES: dict[str, dict[str, str]] = {
    "Default": {
        "Space": "play_pause", "Left": "seek_backward", "Right": "seek_forward",
        "Up": "volume_up", "Down": "volume_down", "M": "mute", "F": "fullscreen",
        "Escape": "exit_fullscreen", "P": "playlist", "T": "always_on_top",
        "S": "screenshot", "Ctrl+O": "open_file", "Ctrl+U": "open_url",
        ".": "next", ",": "previous", "Ctrl+M": "music_mode",
    },
    "VLC-style": {
        "Space": "play_pause", "Left": "seek_backward", "Right": "seek_forward",
        "Up": "volume_up", "Down": "volume_down", "M": "mute", "F": "fullscreen",
        "Escape": "exit_fullscreen", "Ctrl+L": "playlist", "Ctrl+O": "open_file",
        "N": "next", "P": "previous",
    },
}


class KeyBindingStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or app_data_dir() / "keybindings"
        self.directory.mkdir(parents=True, exist_ok=True)

    def profile_names(self) -> list[str]:
        custom = [path.stem for path in self.directory.glob("*.json")]
        return list(BUILTIN_PROFILES) + sorted(name for name in custom if name not in BUILTIN_PROFILES)

    def load(self, name: str) -> dict[str, str]:
        if name in BUILTIN_PROFILES:
            return deepcopy(BUILTIN_PROFILES[name])
        path = self.directory / f"{name}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(key): str(action) for key, action in data.items()}
        except (OSError, ValueError, TypeError):
            return deepcopy(BUILTIN_PROFILES["Default"])

    def save(self, name: str, bindings: dict[str, str]) -> None:
        if name in BUILTIN_PROFILES:
            raise ValueError("Built-in profiles are read-only")
        (self.directory / f"{name}.json").write_text(json.dumps(bindings, indent=2), encoding="utf-8")

    def duplicate(self, source: str, target: str) -> dict[str, str]:
        bindings = self.load(source)
        self.save(target, bindings)
        return bindings

