"""Platform accessibility adaptations used by UI transitions."""

from __future__ import annotations

import os


def system_animations_enabled() -> bool:
    """Respect Windows' Show animations accessibility preference."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(enabled.value) if ok else True
    except (AttributeError, OSError, ValueError):
        return True


def transitions_enabled(settings: object) -> bool:
    return bool(settings.get("ui.animations", True)) and system_animations_enabled()
