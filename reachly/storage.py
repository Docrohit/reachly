"""Tiny SQLite store for post history (used for de-duplication and an audit log).

Self-contained so the standalone agent has no external DB dependency.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class History:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "history.db"
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                theme TEXT,
                hook TEXT,
                body TEXT,
                platform TEXT,
                ok INTEGER,
                permalink TEXT,
                error TEXT
            )
            """
        )
        self._conn.commit()

    def recent_hooks(self, limit: int = 15) -> list[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT hook FROM posts ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [r[0] for r in cur.fetchall() if r[0]]

    def record(self, *, theme, hook, body, platform, ok, permalink=None, error=None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO posts (created_at, theme, hook, body, platform, ok, permalink, error) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    datetime.utcnow().isoformat(),
                    theme,
                    hook,
                    body,
                    platform,
                    1 if ok else 0,
                    permalink,
                    error,
                ),
            )
            self._conn.commit()

    def record_event(self, *, platform: str, ok: bool, error: str, theme: str = "", hook: str = "", body: str = "") -> None:
        self.record(
            theme=theme,
            hook=hook,
            body=body,
            platform=platform,
            ok=ok,
            error=error,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
