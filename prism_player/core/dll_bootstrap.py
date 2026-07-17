"""Deterministic Windows bootstrap for the vendored libmpv DLL."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


_MPV_DLL_HANDLE: ctypes.CDLL | None = None


def application_root() -> Path:
    """Return the development or PyInstaller application root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[2]


def vendored_mpv_path() -> Path:
    """Return the one supported, absolute mpv DLL path."""
    return (application_root() / "bin" / "mpv-2.dll").resolve()


def load_vendored_mpv() -> Path:
    """Load the vendored x64 DLL explicitly before Qt or python-mpv."""
    global _MPV_DLL_HANDLE
    path = vendored_mpv_path()
    if not path.is_file():
        raise FileNotFoundError(f"Vendored mpv DLL not found: {path}")
    if _MPV_DLL_HANDLE is None:
        _MPV_DLL_HANDLE = ctypes.CDLL(str(path))
    return path


def mpv_dll_loaded() -> bool:
    return _MPV_DLL_HANDLE is not None
