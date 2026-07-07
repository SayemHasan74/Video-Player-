"""File scanning and media format detection utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from config.settings import MEDIA_EXTENSIONS, SUBTITLE_EXTENSIONS


def is_media_file(path: Path | str) -> bool:
    """Return True when path has a known media extension."""
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def is_subtitle_file(path: Path | str) -> bool:
    """Return True when path has a known subtitle extension."""
    return Path(path).suffix.lower() in SUBTITLE_EXTENSIONS


def is_probable_url(text: str) -> bool:
    """Return True when text looks like a playable network URL."""
    parsed = urlparse(text.strip())
    return parsed.scheme in {"http", "https", "rtmp", "rtsp", "ftp"} and bool(parsed.netloc)


def scan_media_files(paths: Iterable[Path | str], recursive: bool = False) -> list[Path]:
    """Scan files and folders for media files."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file() and is_media_file(path):
            found.append(path)
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            found.extend(child for child in iterator if child.is_file() and is_media_file(child))
    return sorted(found, key=lambda item: item.name.lower())


def display_name(path_or_url: Path | str) -> str:
    """Return a clean display name."""
    text = str(path_or_url)
    if is_probable_url(text):
        return text
    return Path(text).name or text
