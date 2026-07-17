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
    # ``ui.animations`` is accepted as a migration alias for older settings
    # files, but only the Section 2 disableWindowAnimation preference is shown.
    legacy = settings.get("ui.animations", None)
    enabled = bool(legacy) if legacy is not None else not bool(
        settings.get("ui.disableWindowAnimation", False)
    )
    return enabled and system_animations_enabled()
