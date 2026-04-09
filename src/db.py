"""Database operations using aiosqlite."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from src.config import DATABASE_PATH, FILE_CLEANUP_DELAY
from src.downloader import DownloadPackage


ACTIVE_TASK_STATUSES = ("pending", "queued", "downloading", "downloaded", "sending")


class Database:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DATABASE_PATH)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self):
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def _create_tables(self):
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
            CREATE TABLE IF NOT EXISTS cached_downloads (
                service TEXT NOT NULL,
                url TEXT NOT NULL,
                file_paths TEXT NOT NULL,
                send_as TEXT NOT NULL,
                title TEXT NOT NULL,
                performer TEXT,
                thumbnail TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(service, url)
            )
            """
        )
        await self._connection.execute("CREATE INDEX IF NOT EXISTS idx_user_status ON tasks(user_id, status)")
        await self._connection.execute("CREATE INDEX IF NOT EXISTS idx_sent_at ON tasks(sent_at)")
        await self._connection.execute("CREATE INDEX IF NOT EXISTS idx_cache_updated_at ON cached_downloads(updated_at)")
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

    async def has_active_task(self, user_id: int, url: str, service: str) -> bool:
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        cursor = await self._connection.execute(
            f"""
            SELECT 1
            FROM tasks
            WHERE user_id = ? AND url = ? AND service = ? AND status IN ({placeholders})
            LIMIT 1
            """,
            (user_id, url, service, *ACTIVE_TASK_STATUSES),
        )
        return await cursor.fetchone() is not None

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

    async def cache_download(self, service: str, url: str, package: DownloadPackage):
        await self._connection.execute(
            """
            INSERT INTO cached_downloads (
                service, url, file_paths, send_as, title, performer, thumbnail, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service, url) DO UPDATE SET
                file_paths = excluded.file_paths,
                send_as = excluded.send_as,
                title = excluded.title,
                performer = excluded.performer,
                thumbnail = excluded.thumbnail,
                updated_at = excluded.updated_at
            """,
            (
                service,
                url,
                json.dumps(package.files),
                package.send_as,
                package.title,
                package.performer,
                package.thumbnail,
                int(time.time()),
            ),
        )
        await self._connection.commit()

    async def get_cached_download(self, service: str, url: str) -> Optional[DownloadPackage]:
        cursor = await self._connection.execute(
            """
            SELECT *
            FROM cached_downloads
            WHERE service = ? AND url = ?
            LIMIT 1
            """,
            (service, url),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        payload = dict(row)
        try:
            files = json.loads(payload["file_paths"])
        except json.JSONDecodeError:
            return None
        if not isinstance(files, list) or not files or not all(isinstance(item, str) for item in files):
            return None
        package = DownloadPackage(
            files=files,
            send_as=payload["send_as"],
            title=payload["title"],
            performer=payload["performer"],
            thumbnail=payload["thumbnail"],
        )
        if not all(Path(file_path).exists() for file_path in package.files):
            await self.delete_cached_download(service, url)
            return None
        await self.touch_cached_download(service, url)
        return package

    async def touch_cached_download(self, service: str, url: str):
        await self._connection.execute(
            """
            UPDATE cached_downloads
            SET updated_at = ?
            WHERE service = ? AND url = ?
            """,
            (int(time.time()), service, url),
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

    async def get_cached_downloads_for_cleanup(self) -> List[Dict[str, Any]]:
        threshold = int(time.time()) - FILE_CLEANUP_DELAY
        cursor = await self._connection.execute(
            """
            SELECT *
            FROM cached_downloads
            WHERE updated_at <= ?
            """,
            (threshold,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_task(self, task_id: int):
        await self._connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await self._connection.commit()

    async def delete_cached_download(self, service: str, url: str):
        await self._connection.execute(
            "DELETE FROM cached_downloads WHERE service = ? AND url = ?",
            (service, url),
        )
        await self._connection.commit()

    async def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        cursor = await self._connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


db = Database()


async def init_db() -> Database:
    await db.connect()
    return db
