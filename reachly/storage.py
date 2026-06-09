"""Tiny SQLite store for post history (used for de-duplication and an audit log).

Self-contained so the standalone agent has no external DB dependency.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
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
        self._ensure_columns(
            "posts",
            {
                "impressions": "INTEGER",
                "likes": "INTEGER",
                "comments": "INTEGER",
                "shares": "INTEGER",
                "analytics_checked_at": "TEXT",
                "analytics_note": "TEXT",
            },
        )
        self._conn.commit()

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {
            row[1]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def recent_hooks(self, limit: int = 15) -> list[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT hook FROM posts ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [r[0] for r in cur.fetchall() if r[0]]

    def recent_themes(self, limit: int = 5) -> list[str]:
        """Return recently successful distinct themes, newest first."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT theme
                FROM posts
                WHERE ok = 1 AND theme != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit * 4,),
            )
            out = []
            seen = set()
            for (theme,) in cur.fetchall():
                key = theme.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(theme)
                if len(out) >= limit:
                    break
            return out

    def recent_platform_posts(self, platform: str | None = None, limit: int = 3) -> list[dict]:
        query = (
            "SELECT id, created_at, theme, hook, body, platform, ok, permalink, error, "
            "impressions, likes, comments, shares, analytics_note "
            "FROM posts WHERE hook != ''"
        )
        params: list[object] = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(query, params)
            return [_row_to_dict(row) for row in cur.fetchall()]

    def analytics_summary(self, *, days: int = 14, limit: int = 12) -> str:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, created_at, theme, hook, body, platform, ok, permalink, error,
                       impressions, likes, comments, shares, analytics_note
                FROM posts
                WHERE created_at >= ? AND ok = 1
                ORDER BY id DESC
                LIMIT ?
                """,
                (cutoff, limit),
            )
            rows = [_row_to_dict(row) for row in cur.fetchall()]
        if not rows:
            return "No successful historical posts are recorded yet."

        lines = []
        for row in rows:
            metrics = _metrics_text(row)
            note = (row.get("analytics_note") or "").strip()
            text = f"- {row['platform']} | {row['theme']} | {row['hook']}"
            if metrics:
                text += f" | {metrics}"
            if note:
                text += f" | note: {note[:180]}"
            lines.append(text)
        return "\n".join(lines)

    def newness_summary(self, limit_per_platform: int = 3) -> str:
        platforms = ["linkedin", "instagram", "twitter"]
        sections = []
        for platform in platforms:
            rows = self.recent_platform_posts(platform, limit_per_platform)
            if not rows:
                continue
            bullets = "\n".join(
                f"  - {row['theme']}: {row['hook']}" for row in rows if row.get("hook")
            )
            if bullets:
                sections.append(f"{platform} last {len(rows)} posts:\n{bullets}")
        return "\n".join(sections)

    def record(
        self,
        *,
        theme,
        hook,
        body,
        platform,
        ok,
        permalink=None,
        error=None,
        impressions: int | None = None,
        likes: int | None = None,
        comments: int | None = None,
        shares: int | None = None,
        analytics_note: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO posts (created_at, theme, hook, body, platform, ok, permalink, error, "
                "impressions, likes, comments, shares, analytics_note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.utcnow().isoformat(),
                    theme,
                    hook,
                    body,
                    platform,
                    1 if ok else 0,
                    permalink,
                    error,
                    impressions,
                    likes,
                    comments,
                    shares,
                    analytics_note,
                ),
            )
            self._conn.commit()

    def record_analytics(
        self,
        post_id: int,
        *,
        impressions: int | None = None,
        likes: int | None = None,
        comments: int | None = None,
        shares: int | None = None,
        note: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE posts
                SET impressions = COALESCE(?, impressions),
                    likes = COALESCE(?, likes),
                    comments = COALESCE(?, comments),
                    shares = COALESCE(?, shares),
                    analytics_note = COALESCE(?, analytics_note),
                    analytics_checked_at = ?
                WHERE id = ?
                """,
                (
                    impressions,
                    likes,
                    comments,
                    shares,
                    note,
                    datetime.utcnow().isoformat(),
                    post_id,
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


def _row_to_dict(row: tuple) -> dict:
    keys = [
        "id",
        "created_at",
        "theme",
        "hook",
        "body",
        "platform",
        "ok",
        "permalink",
        "error",
        "impressions",
        "likes",
        "comments",
        "shares",
        "analytics_note",
    ]
    return dict(zip(keys, row))


def _metrics_text(row: dict) -> str:
    parts = []
    for key in ("impressions", "likes", "comments", "shares"):
        value = row.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    return ", ".join(parts)
