"""Section 2 OSC facade: one controller and one shared widget set."""

from ui.control_bar import ControlBar
from ui.overlay_controller import OverlayController


class OscController(OverlayController):
    """Own the shared OSC placement and its single-shot visibility timer."""


__all__ = ["ControlBar", "OscController"]
