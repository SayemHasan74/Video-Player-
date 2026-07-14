"""Per-media visual state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import app_data_dir


class MediaStateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "media_state.json"

    @staticmethod
    def key(source: str) -> str:
        if "://" in source:
            return source
        try:
            return str(Path(source).expanduser().resolve()).casefold()
        except OSError:
            return source.casefold()

    def get(self, source: str) -> dict[str, Any]:
        return dict(self._read().get(self.key(source), {}))

    def update(self, source: str, **values: Any) -> None:
        data = self._read()
        current = dict(data.get(self.key(source), {}))
        current.update(values)
        data[self.key(source)] = current
        # Keep this lightweight even for users with very large libraries.
        if len(data) > 1000:
            data = dict(list(data.items())[-1000:])
        self._write(data)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.path)
