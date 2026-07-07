"""SQLite playback history storage."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from config.settings import app_data_dir


class HistoryManager:
    """Save and restore playback positions."""

    def __init__(self, path: Path | None = None) -> None:
        self.logger = logging.getLogger(__name__)
        self.path = path or app_data_dir() / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS playback_history (
                source TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                position REAL NOT NULL,
                duration REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def save_position(self, source: str, title: str, position: float, duration: float) -> None:
        """Persist playback position."""
        if duration <= 30 or position < 5 or position >= duration - 10:
            return
        try:
            self.connection.execute(
                """
                INSERT INTO playback_history(source, title, position, duration, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source) DO UPDATE SET
                    title=excluded.title,
                    position=excluded.position,
                    duration=excluded.duration,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (source, title, float(position), float(duration)),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.logger.warning("Could not save history: %s", exc)

    def resume_position(self, source: str) -> float:
        """Return saved position for source."""
        try:
            row = self.connection.execute("SELECT position, duration FROM playback_history WHERE source=?", (source,)).fetchone()
        except sqlite3.Error as exc:
            self.logger.warning("Could not read history: %s", exc)
            return 0.0
        if not row:
            return 0.0
        position, duration = float(row[0]), float(row[1])
        if duration > 0 and position < duration - 10:
            return position
        return 0.0

    def close(self) -> None:
        """Close the database."""
        self.connection.close()
