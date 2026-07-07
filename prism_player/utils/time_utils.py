"""Time formatting helpers."""

from __future__ import annotations


def format_time(seconds: float | int | None) -> str:
    """Format seconds as H:MM:SS or MM:SS."""
    try:
        total = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_time_pair(position: float, duration: float) -> str:
    """Format current and total playback time."""
    return f"{format_time(position)} / {format_time(duration)}"
