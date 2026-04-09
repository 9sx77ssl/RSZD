"""Background cleanup task."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from src.config import CLEANUP_INTERVAL, DOWNLOAD_DIR


def _extract_paths(raw_value: str | None) -> list[Path]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
        if isinstance(payload, list):
            return [Path(item) for item in payload if isinstance(item, str)]
    except json.JSONDecodeError:
        pass
    return [Path(raw_value)]


class CleanupManager:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, db):
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop(db))
        return self._task

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _cleanup_loop(self, db):
        while self._running:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._perform_cleanup(db)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[Cleanup] Loop error: {exc}")

    async def _perform_cleanup(self, db):
        cached_entries = await db.get_cached_downloads_for_cleanup()
        for entry in cached_entries:
            for path in _extract_paths(entry.get("file_paths")):
                if path.exists():
                    try:
                        path.unlink()
                        print(f"[Cleanup] Deleted cached file: {path}")
                    except OSError as exc:
                        print(f"[Cleanup] Failed to delete {path}: {exc}")
            await db.delete_cached_download(entry["service"], entry["url"])
            print(f"[Cleanup] Deleted cache entry: {entry['service']} {entry['url']}")

        tasks = await db.get_tasks_for_cleanup()
        for task in tasks:
            await db.delete_task(task["id"])
            print(f"[Cleanup] Deleted task record: {task['id']}")

        for path in DOWNLOAD_DIR.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() == ".part":
                try:
                    path.unlink()
                    print(f"[Cleanup] Removed stale partial file: {path}")
                except OSError as exc:
                    print(f"[Cleanup] Failed to remove stale file {path}: {exc}")


cleanup_manager = CleanupManager()


async def start_cleanup_task(db) -> asyncio.Task:
    return await cleanup_manager.start(db)


async def stop_cleanup_task():
    await cleanup_manager.stop()
