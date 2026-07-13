"""Persistent named video/audio filter presets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import app_data_dir


class FilterStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "filters.json"

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        result = []
        for index, item in enumerate(raw):
            if isinstance(item, str):
                result.append({"name": f"Preset {index + 1}", "kind": "video", "value": item, "shortcut": "", "enabled": False})
            elif isinstance(item, dict) and item.get("value"):
                result.append({
                    "name": str(item.get("name") or f"Preset {index + 1}"),
                    "kind": "audio" if item.get("kind") == "audio" else "video",
                    "value": str(item["value"]),
                    "shortcut": str(item.get("shortcut") or ""),
                    "enabled": bool(item.get("enabled", False)),
                })
        return result

    def save(self, presets: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(presets, indent=2), encoding="utf-8")
        temporary.replace(self.path)
