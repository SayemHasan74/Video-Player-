"""Network URL resolver built on yt-dlp."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class UrlResolverWorker(QThread):
    """Resolve a media URL without blocking the UI."""

    resolved = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(self, url: str, preferred_format: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.preferred_format = preferred_format

    def run(self) -> None:
        """Resolve URL through yt-dlp."""
        try:
            import yt_dlp

            options = {
                "quiet": True,
                "no_warnings": True,
                "format": self.preferred_format,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=False)
            if "url" in info:
                self.resolved.emit(info["url"], info.get("title") or self.url)
                return
            formats = info.get("formats") or []
            if formats:
                self.resolved.emit(formats[-1]["url"], info.get("title") or self.url)
                return
            self.failed.emit("No playable stream found")
        except Exception as exc:
            self.failed.emit(str(exc))
