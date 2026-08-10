"""طبقة بسيطة للتعامل مع قاعدة بيانات SQLite: المستخدمين، الاستخدام اليومي، والاشتراكات"""

import sqlite3
from contextlib import contextmanager


class Database:
    def __init__(self, path: str = "bot_data.db"):
        self.path = path

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    user_id INTEGER,
                    day TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, day)
                )
                """
            )

    def ensure_user(self, user_id: int):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
            )

    def is_premium(self, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT is_premium FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row[0])

    def set_premium(self, user_id: int, premium: bool = True):
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_premium = ? WHERE user_id = ?",
                (1 if premium else 0, user_id),
            )

    def get_usage_count(self, user_id: int, day: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count FROM usage WHERE user_id = ? AND day = ?",
                (user_id, day),
            ).fetchone()
            return row[0] if row else 0

    def increment_usage(self, user_id: int, day: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage (user_id, day, count) VALUES (?, ?, 1)
                ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
                """,
                (user_id, day),
            )
