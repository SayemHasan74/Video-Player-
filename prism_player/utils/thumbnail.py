"""Thumbnail placeholder utilities."""

from __future__ import annotations

from pathlib import Path


def thumbnail_path_for(source: Path | str) -> Path:
    """Return a deterministic placeholder path for future thumbnails."""
    safe = str(source).replace(":", "").replace("\\", "_").replace("/", "_")
    return Path.home() / "AppData" / "Roaming" / "CometPlayer" / "thumbs" / f"{safe}.jpg"
