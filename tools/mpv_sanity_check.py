"""Pre-Qt development check for the vendored libmpv and real playback."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path, help="A real local audio/video test file")
    args = parser.parse_args()
    media = args.media.expanduser().resolve()
    if not media.is_file():
        parser.error(f"media file does not exist: {media}")
    dll = (Path(__file__).resolve().parents[1] / "bin" / "mpv-2.dll").resolve()
    ctypes.CDLL(str(dll))
    original = ctypes.util.find_library
    ctypes.util.find_library = lambda name: str(dll) if name.casefold() in {
        "mpv-1.dll", "mpv-2.dll", "libmpv-2.dll"
    } else original(name)
    try:
        import mpv
    finally:
        ctypes.util.find_library = original
    player = mpv.MPV(loglevel="warn")
    try:
        player.play(str(media))
        player.wait_for_playback()
    finally:
        player.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
