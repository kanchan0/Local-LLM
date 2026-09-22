from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    last_seen_at TEXT,
    session_version INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserDatabase:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            for column, definition in (("last_login_at", "TEXT"), ("last_seen_at", "TEXT"), ("session_version", "INTEGER NOT NULL DEFAULT 0")):
                if column not in columns:
                    connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, role, enabled, created_at, last_login_at, last_seen_at, session_version "
                "FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, role, enabled, created_at, last_login_at, last_seen_at, session_version "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, password_hash: str, role: str = "user") -> int:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("username cannot be empty")
        if role not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users(username, password_hash, role, enabled, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (clean_username, password_hash, role, _now()),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def set_enabled(self, username: str, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET enabled = ? WHERE username = ?",
                (1 if enabled else 0, username.strip()),
            )
            connection.commit()

    def set_enabled_by_id(self, user_id: int, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE users SET enabled = ? WHERE id = ?", (1 if enabled else 0, user_id))
            if not enabled:
                connection.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (user_id,))
            connection.commit()

    def set_password(self, user_id: int, password_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                (password_hash, user_id),
            )
            connection.commit()

    def record_login(self, user_id: int) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ?, last_seen_at = ? WHERE id = ?",
                (now, now, user_id),
            )
            connection.commit()

    def revoke_sessions(self, user_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (user_id,))
            connection.commit()

    def record_seen(self, user_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (_now(), user_id))
            connection.commit()

    def list_users(self, active_window_seconds: int = 300) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, enabled, created_at, last_login_at, last_seen_at, session_version "
                "FROM users ORDER BY username"
            ).fetchall()
        now = datetime.now(timezone.utc)
        users = []
        for row in rows:
            user = dict(row)
            try:
                last_seen = datetime.fromisoformat(user["last_seen_at"]) if user["last_seen_at"] else None
            except ValueError:
                last_seen = None
            user["active"] = bool(
                user["enabled"] and last_seen and (now - last_seen).total_seconds() <= active_window_seconds
            )
            users.append(user)
        return users
