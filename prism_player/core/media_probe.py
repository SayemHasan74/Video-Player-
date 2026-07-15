"""Background-friendly media metadata probing and subtitle matching."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import re
from difflib import SequenceMatcher
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
        # ffprobe writes UTF-8 JSON regardless of the Windows ANSI code page.
        # Letting subprocess use text=True can therefore crash its reader
        # thread on paths/tags containing emoji or other non-CP1252 text.
        result = subprocess.run(command, capture_output=True, timeout=20, creationflags=0x08000000)
        if result.returncode != 0 or not result.stdout:
            return {}
        payload = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout)
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, UnicodeError):
        return {}


def matching_subtitles(source: str) -> list[Path]:
    path = Path(source)
    if not path.exists():
        return []
    def normalized(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
    stem = normalized(path.stem)
    matches: list[tuple[float, Path]] = []
    for child in path.parent.iterdir():
        if not child.is_file() or child.suffix.lower() not in SUBTITLE_EXTENSIONS:
            continue
        candidate = normalized(child.stem)
        ratio = SequenceMatcher(None, stem, candidate).ratio()
        if stem in candidate or candidate in stem or ratio >= 0.68:
            exact_bonus = 1.0 if candidate == stem else 0.5 if candidate.startswith(stem) else 0.0
            matches.append((ratio + exact_bonus, child))
    return [child for _score, child in sorted(matches, key=lambda item: (-item[0], item[1].name.casefold()))]
