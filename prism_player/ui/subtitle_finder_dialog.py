"""Online subtitle finder helper."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton, QVBoxLayout


class SubtitleFinderDialog(QDialog):
    """Open subtitle searches and load downloaded subtitle files."""

    subtitleSelected = pyqtSignal(str)

    def __init__(self, media_source: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.media_source = media_source
        self.setWindowTitle("Find Subtitles")
        query = self._query_from_source(media_source)
        label = QLabel(query or "Current media", self)
        label.setWordWrap(True)
        open_subtitles = QPushButton("Search OpenSubtitles", self)
        subscene = QPushButton("Search web", self)
        load = QPushButton("Load downloaded subtitle", self)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(open_subtitles)
        layout.addWidget(subscene)
        layout.addWidget(load)
        open_subtitles.clicked.connect(lambda: webbrowser.open(f"https://www.opensubtitles.com/en/search/sublanguageid-all/query-{quote_plus(query)}"))
        subscene.clicked.connect(lambda: webbrowser.open(f"https://www.google.com/search?q={quote_plus(query + ' subtitle')}"))
        load.clicked.connect(self._load_downloaded)

    def _load_downloaded(self) -> None:
        start_dir = str(Path(self.media_source).parent) if self.media_source and Path(self.media_source).exists() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Load Subtitle", start_dir, "Subtitle files (*.srt *.ass *.ssa *.sub *.vtt)")
        if path:
            self.subtitleSelected.emit(path)
            self.accept()

    def _query_from_source(self, source: str) -> str:
        if source and not source.startswith(("http://", "https://")):
            return Path(source).stem
        return source
