"""Persistent playback history with queued background writes."""

from __future__ import annotations

import logging
import queue
import sqlite3
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread

from config.settings import app_data_dir


SCHEMA = """
CREATE TABLE IF NOT EXISTS playback_history (
    source TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    position REAL NOT NULL,
    duration REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class HistoryWriter(QThread):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.tasks: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()

    def submit(self, operation: str, *values: Any) -> None:
        self.tasks.put((operation, values))

    def run(self) -> None:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(SCHEMA)
        connection.commit()
        try:
            while True:
                operation, values = self.tasks.get()
                try:
                    if operation == "stop":
                        return
                    if operation == "save":
                        connection.execute(
                            """
                            INSERT INTO playback_history(source,title,position,duration,updated_at)
                            VALUES (?,?,?,?,CURRENT_TIMESTAMP)
                            ON CONFLICT(source) DO UPDATE SET title=excluded.title,
                                position=excluded.position,duration=excluded.duration,
                                updated_at=CURRENT_TIMESTAMP
                            """,
                            values,
                        )
                    elif operation == "remove":
                        connection.execute("DELETE FROM playback_history WHERE source=?", values)
                    elif operation == "clear":
                        connection.execute("DELETE FROM playback_history")
                    connection.commit()
                except sqlite3.Error as exc:
                    connection.rollback()
                    logging.getLogger(__name__).warning("History write failed: %s", exc)
                finally:
                    self.tasks.task_done()
        finally:
            connection.close()


class HistoryManager:
    """Read history synchronously and serialize writes away from playback/UI threads."""

    def __init__(self, path: Path | None = None) -> None:
        self.logger = logging.getLogger(__name__)
        self.path = path or app_data_dir() / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(SCHEMA)
        self.connection.commit()
        self.writer = HistoryWriter(self.path)
        self.writer.start()

    def save_position(self, source: str, title: str, position: float, duration: float) -> None:
        if duration <= 30 or position < 5:
            return
        self.writer.submit("save", source, title, min(float(position), float(duration)), float(duration))

    def resume_position(self, source: str) -> float:
        self.flush()
        try:
            row = self.connection.execute("SELECT position,duration FROM playback_history WHERE source=?", (source,)).fetchone()
        except sqlite3.Error as exc:
            self.logger.warning("Could not read history: %s", exc)
            return 0.0
        if not row:
            return 0.0
        position, duration = float(row[0]), float(row[1])
        return position if duration > 0 and position < duration - 10 else 0.0

    def entries(self, query: str = "", exclude_source: str = "") -> list[dict]:
        self.flush()
        clauses = []
        params: list[str] = []
        if query:
            clauses.append("(title LIKE ? OR source LIKE ?)")
            params.extend((f"%{query}%", f"%{query}%"))
        if exclude_source:
            clauses.append("source != ?")
            params.append(exclude_source)
        sql = "SELECT source,title,position,duration,updated_at FROM playback_history"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        try:
            rows = self.connection.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            self.logger.warning("Could not list history: %s", exc)
            return []
        keys = ("source", "title", "position", "duration", "updated_at")
        return [dict(zip(keys, row)) for row in rows]

    def remove(self, source: str) -> None:
        self.writer.submit("remove", source)

    def clear(self) -> None:
        self.writer.submit("clear")

    def flush(self, timeout_ms: int = 1000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while self.writer.tasks.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.005)
        return not self.writer.tasks.unfinished_tasks

    def close(self) -> None:
        self.flush(2000)
        self.writer.submit("stop")
        self.writer.wait(2000)
        self.connection.close()
