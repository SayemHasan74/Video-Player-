"""Background-friendly media metadata probing and subtitle matching."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from config.settings import SUBTITLE_EXTENSIONS


@lru_cache(maxsize=2048)
def probe_media(source: str) -> dict:
    path = Path(source)
    if not path.exists():
        return {}
    ffprobe = shutil.which("ffprobe")
    if not ffprobe and os.name == "nt":
        link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe"
        ffprobe = str(link) if link.exists() else None
        if not ffprobe:
            packages=Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"WinGet"/"Packages"
            match=next(packages.glob("Gyan.FFmpeg*/**/ffprobe.exe"),None)
            ffprobe=str(match) if match else None
    if not ffprobe: return {}
    command = [ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        return json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def matching_subtitles(source: str) -> list[Path]:
    path = Path(source)
    if not path.exists():
        return []
    stem = path.stem.casefold()
    return sorted(
        child for child in path.parent.iterdir()
        if child.is_file() and child.suffix.lower() in SUBTITLE_EXTENSIONS
        and (child.stem.casefold().startswith(stem) or stem.startswith(child.stem.casefold()))
    )
