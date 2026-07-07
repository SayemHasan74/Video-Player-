"""Small inline SVG icon factory."""

from __future__ import annotations

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QIcon, QPixmap


PATHS: dict[str, str] = {
    "prism": '<path d="M12 2 3 20h18L12 2Zm0 5.4 4.6 9.2H7.4L12 7.4Z"/>',
    "play": '<path d="M8 5v14l11-7L8 5Z"/>',
    "pause": '<path d="M7 5h4v14H7V5Zm6 0h4v14h-4V5Z"/>',
    "stop": '<path d="M6 6h12v12H6V6Z"/>',
    "prev_track": '<path d="M6 5h2v14H6V5Zm3 7 10 7V5L9 12Z"/>',
    "next_track": '<path d="M16 5h2v14h-2V5ZM5 5v14l10-7L5 5Z"/>',
    "volume": '<path d="M4 9v6h4l5 4V5L8 9H4Zm12.5-2a7 7 0 0 1 0 10l1.4 1.4a9 9 0 0 0 0-12.8L16.5 7Z"/>',
    "mute": '<path d="M4 9v6h4l5 4V5L8 9H4Zm12.2 3-2.1-2.1 1.4-1.4 2.1 2.1 2.1-2.1 1.4 1.4L19 12l2.1 2.1-1.4 1.4-2.1-2.1-2.1 2.1-1.4-1.4 2.1-2.1Z"/>',
    "fullscreen": '<path d="M5 5h6v2H7v4H5V5Zm8 0h6v6h-2V7h-4V5ZM7 13v4h4v2H5v-6h2Zm12 0v6h-6v-2h4v-4h2Z"/>',
    "fullscreen_exit": '<path d="M9 5h2v6H5V9h4V5Zm4 0h2v4h4v2h-6V5ZM5 13h6v6H9v-4H5v-2Zm14 0v2h-4v4h-2v-6h6Z"/>',
    "minimize": '<path d="M5 12h14v2H5v-2Z"/>',
    "maximize": '<path d="M6 6h12v12H6V6Zm2 2v8h8V8H8Z"/>',
    "restore": '<path d="M8 5h11v11h-3v3H5V8h3V5Zm2 3h6v6h1V7h-7v1Zm-3 3v6h7v-6H7Z"/>',
    "close": '<path d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4 6.4 5Z"/>',
    "playlist_toggle": '<path d="M4 6h12v2H4V6Zm0 5h12v2H4v-2Zm0 5h8v2H4v-2Zm13-1 4 2.5-4 2.5v-5Z"/>',
    "pip": '<path d="M4 5h16v14H4V5Zm2 2v10h12V7H6Zm7 5h4v3h-4v-3Z"/>',
    "cover": '<path d="M4 6h16v12H4V6Zm2 2v8h12V8H6Zm2 1h8v6H8V9Z"/>',
    "subtitle": '<path d="M4 6h16v12H4V6Zm2 2v8h12V8H6Zm1 5h5v1.5H7V13Zm6 0h4v1.5h-4V13Z"/>',
    "audio_track": '<path d="M9 18a3 3 0 1 1 0-6c.7 0 1.4.2 2 .7V5h8v3h-6v10h-2v-1.1c-.5.7-1.2 1.1-2 1.1Z"/>',
    "screenshot": '<path d="M8 6 9.5 4h5L16 6h4v13H4V6h4Zm4 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/>',
    "ab_loop": '<path d="M5 7h5v2H7v6h3v2H5V7Zm9 0h5v10h-5v-2h3V9h-3V7ZM9 12h6v2H9v-2Z"/>',
    "folder": '<path d="M3 6h7l2 2h9v10H3V6Z"/>',
}


def svg_icon(name: str, color: str = "#c0c0c0", size: int = 24) -> QIcon:
    """Create a QIcon from an inline SVG path."""
    path = PATHS.get(name, PATHS["prism"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="{color}">{path}</svg>'
    )
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg.encode("utf-8")), "SVG")
    return QIcon(pixmap)
