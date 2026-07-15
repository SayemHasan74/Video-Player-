"""File, playlist, folder, and basic Blu-ray input utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from config.settings import MEDIA_EXTENSIONS, SUBTITLE_EXTENSIONS


PLAYLIST_EXTENSIONS = frozenset({".m3u", ".m3u8"})


@dataclass(frozen=True)
class InputEntry:
    source: str
    title: str = ""
    autoload_subtitles: bool = True
    title_explicit: bool = False


def is_media_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def is_playlist_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in PLAYLIST_EXTENSIONS


def is_subtitle_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUBTITLE_EXTENSIONS


def is_probable_url(text: str) -> bool:
    parsed = urlparse(text.strip())
    return parsed.scheme in {"http", "https", "rtmp", "rtsp", "ftp"} and bool(parsed.netloc)


def parse_m3u(path: Path | str) -> list[InputEntry]:
    """Parse M3U/M3U8 entries relative to the playlist's own directory."""
    playlist = Path(path)
    try:
        raw = playlist.read_bytes()
    except OSError:
        return []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    entries: list[InputEntry] = []
    pending_title = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF:"):
            _prefix, _comma, pending_title = line.partition(",")
            pending_title = pending_title.strip()
            continue
        if line.startswith("#"):
            continue
        if line.lower().startswith("file://"):
            parsed = urlparse(line)
            source: str | Path = Path(unquote(parsed.path.lstrip("/") if os.name == "nt" else parsed.path))
        elif is_probable_url(line):
            source = line
        else:
            candidate = Path(line.strip('"'))
            source = candidate if candidate.is_absolute() else playlist.parent / candidate
            source = source.resolve()
        entries.append(InputEntry(
            str(source), pending_title or display_name(source),
            autoload_subtitles=False, title_explicit=bool(pending_title),
        ))
        pending_title = ""
    return entries


def bdmv_root(path: Path | str) -> Path | None:
    """Return the BDMV directory containing a selected file/folder, if any."""
    candidate = Path(path)
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if directory.name.casefold() == "bdmv" and (directory / "STREAM").is_dir():
            return directory
        child = directory / "BDMV"
        if child.is_dir() and (child / "STREAM").is_dir():
            return child
    return None


def resolve_bdmv_main_title(path: Path | str) -> Path | None:
    """Choose the largest transport stream as a basic playable main title."""
    root = bdmv_root(path)
    if root is None:
        return None
    streams = [entry for entry in (root / "STREAM").glob("*.m2ts") if entry.is_file()]
    if not streams:
        return None
    return max(streams, key=lambda entry: (entry.stat().st_size, entry.name.casefold()))


def scan_media_files(paths: Iterable[Path | str], recursive: bool = False) -> list[Path]:
    """Scan media while collapsing every discovered BDMV tree to one title."""
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            found.append(path.resolve())

    for raw in paths:
        path = Path(raw)
        main_title = resolve_bdmv_main_title(path)
        if main_title is not None:
            add(main_title)
            continue
        if path.is_file() and is_media_file(path):
            add(path)
        elif path.is_dir():
            if not recursive:
                for child in path.iterdir():
                    if child.is_dir() and child.name.casefold() == "bdmv":
                        title = resolve_bdmv_main_title(child)
                        if title is not None:
                            add(title)
                    elif child.is_file() and is_media_file(child):
                        add(child)
                continue
            for root_text, directories, filenames in os.walk(path):
                root = Path(root_text)
                if root.name.casefold() == "bdmv":
                    title = resolve_bdmv_main_title(root)
                    if title is not None:
                        add(title)
                    directories[:] = []
                    continue
                bdmv_names = [name for name in directories if name.casefold() == "bdmv"]
                for name in bdmv_names:
                    title = resolve_bdmv_main_title(root / name)
                    if title is not None:
                        add(title)
                    directories.remove(name)
                for name in filenames:
                    child = root / name
                    if is_media_file(child):
                        add(child)
    return sorted(found, key=lambda item: (item.name.casefold(), str(item).casefold()))


def expand_input_paths(paths: Iterable[Path | str], recursive_folders: bool = True) -> tuple[list[InputEntry], bool]:
    """Resolve explicit inputs and report whether playlist-file scoping applies."""
    inputs = [Path(path) for path in paths]
    explicit_playlist = any(path.is_file() and is_playlist_file(path) for path in inputs)
    entries: list[InputEntry] = []
    seen: set[str] = set()
    for path in inputs:
        if path.is_file() and is_playlist_file(path):
            candidates = parse_m3u(path)
        elif path.is_dir():
            candidates = [InputEntry(str(item), display_name(item), True) for item in scan_media_files([path], recursive_folders)]
        else:
            main_title = resolve_bdmv_main_title(path)
            candidate = main_title or path
            candidates = [InputEntry(str(candidate), display_name(candidate), True)] if is_media_file(candidate) else []
        for entry in candidates:
            key = entry.source.casefold()
            if key not in seen:
                seen.add(key)
                entries.append(entry)
    return entries, explicit_playlist


def display_name(path_or_url: Path | str) -> str:
    text = str(path_or_url)
    if is_probable_url(text):
        return text
    return Path(text).name or text
