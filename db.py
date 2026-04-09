"""
Database operations using aiosqlite.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import aiosqlite

from config import DATABASE_PATH, FILE_CLEANUP_DELAY


class Database:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DATABASE_PATH)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Establish database connection."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self):
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def _create_tables(self):
        """Create database tables if they don't exist."""
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                service TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT,
                created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                sent_at INTEGER
            )
            """
        )
        await self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_status
            ON tasks(user_id, status)
            """
        )
        await self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sent_at
            ON tasks(sent_at)
            """
        )
        await self._connection.commit()

    async def create_task(self, user_id: int, url: str, service: str) -> int:
        cursor = await self._connection.execute(
            """
            INSERT INTO tasks (user_id, url, service, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (user_id, url, service),
        )
        await self._connection.commit()
        return cursor.lastrowid

    async def update_task_status(self, task_id: int, status: str, file_path: Optional[str] = None):
        if file_path is not None:
            await self._connection.execute(
                """
                UPDATE tasks
                SET status = ?, file_path = ?
                WHERE id = ?
                """,
                (status, file_path, task_id),
            )
        else:
            await self._connection.execute(
                """
                UPDATE tasks
                SET status = ?
                WHERE id = ?
                """,
                (status, task_id),
            )
        await self._connection.commit()

    async def mark_task_sent(self, task_id: int):
        await self._connection.execute(
            """
            UPDATE tasks
            SET status = 'sent', sent_at = ?
            WHERE id = ?
            """,
            (int(time.time()), task_id),
        )
        await self._connection.commit()

    async def get_tasks_for_cleanup(self) -> List[Dict[str, Any]]:
        threshold = int(time.time()) - FILE_CLEANUP_DELAY
        cursor = await self._connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = 'sent' AND sent_at IS NOT NULL AND sent_at <= ?
            """,
            (threshold,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_task(self, task_id: int):
        await self._connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await self._connection.commit()

    async def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        cursor = await self._connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


db = Database()


async def init_db() -> Database:
    await db.connect()
    return db
