"""Incremental ffmpeg thumbnail generation with disk caching."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from config.settings import app_data_dir


def thumbnail_cache_dir(source: Path | str) -> Path:
    path = Path(source)
    try:
        stat = path.stat(); key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        key = str(path)
    target = app_data_dir() / "thumbnails" / hashlib.sha256(key.encode()).hexdigest()
    target.mkdir(parents=True, exist_ok=True)
    return target

def ffmpeg_executable() -> str | None:
    found=shutil.which("ffmpeg")
    if found:return found
    if os.name=="nt":
        link=Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"WinGet"/"Links"/"ffmpeg.exe"
        if link.exists():return str(link)
        packages=Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"WinGet"/"Packages"
        match=next(packages.glob("Gyan.FFmpeg*/**/ffmpeg.exe"),None)
        if match:return str(match)
    return None

def valid_jpeg(path: Path) -> bool:
    try:
        if path.stat().st_size < 4:return False
        with path.open("rb") as handle:
            start=handle.read(2);handle.seek(-2,2);end=handle.read(2)
        return start==b"\xff\xd8" and end==b"\xff\xd9"
    except OSError:return False


class ThumbnailWorker(QThread):
    thumbnailReady = pyqtSignal(float, str)
    progressChanged = pyqtSignal(int)

    def __init__(self, source: str, duration: float, samples: int = 100, parent: object | None = None) -> None:
        super().__init__(parent); self.source = source; self.duration = duration; self.samples = max(1, samples); self._cancelled = False

    def cancel(self) -> None: self._cancelled = True

    def run(self) -> None:
        ffmpeg = ffmpeg_executable()
        if not ffmpeg or self.duration <= 0:
            return
        cache = thumbnail_cache_dir(self.source)
        for index in range(self.samples):
            if self._cancelled: return
            timestamp = self.duration * index / max(1, self.samples - 1); output = cache / f"{index:03d}.jpg"
            if output.exists() and not valid_jpeg(output):
                try: output.unlink()
                except OSError: pass
            if not output.exists():
                command = [ffmpeg, "-loglevel", "error", "-ss", str(timestamp), "-i", self.source, "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "5", "-y", str(output)]
                try: subprocess.run(command, timeout=20, creationflags=0x08000000)
                except (OSError, subprocess.SubprocessError): continue
            if output.exists() and valid_jpeg(output): self.thumbnailReady.emit(timestamp, str(output))
            self.progressChanged.emit(int((index + 1) * 100 / self.samples))


def trim_thumbnail_cache(limit_mb: int) -> None:
    root = app_data_dir() / "thumbnails"
    if not root.exists(): return
    files = sorted((p for p in root.rglob("*.jpg")), key=lambda p: p.stat().st_atime)
    total = sum(p.stat().st_size for p in files); limit = limit_mb * 1024 * 1024
    for path in files:
        if total <= limit: break
        try: size = path.stat().st_size; path.unlink(); total -= size
        except OSError: pass
