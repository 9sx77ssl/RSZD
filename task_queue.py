"""
FIFO queue system per user.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional


@dataclass
class QueueTask:
    task_id: int
    user_id: int
    url: str
    service: str
    message_id: int
    chat_id: int


class UserQueueManager:
    def __init__(self):
        self._queues: Dict[int, asyncio.Queue[QueueTask]] = {}
        self._workers: Dict[int, asyncio.Task] = {}
        self._processing: Dict[int, bool] = {}
        self._process_callback: Optional[Callable[[QueueTask], Awaitable[None]]] = None

    def set_process_callback(self, callback: Callable[[QueueTask], Awaitable[None]]):
        self._process_callback = callback

    def _get_queue(self, user_id: int) -> asyncio.Queue[QueueTask]:
        if user_id not in self._queues:
            self._queues[user_id] = asyncio.Queue()
        return self._queues[user_id]

    async def add_task(self, task: QueueTask):
        queue = self._get_queue(task.user_id)
        await queue.put(task)
        if task.user_id not in self._workers or self._workers[task.user_id].done():
            self._workers[task.user_id] = asyncio.create_task(self._worker(task.user_id))

    async def _worker(self, user_id: int):
        queue = self._get_queue(user_id)
        while True:
            try:
                try:
                    task = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    break

                self._processing[user_id] = True
                try:
                    if self._process_callback:
                        await self._process_callback(task)
                except Exception as exc:
                    print(f"[Queue] Error processing task {task.task_id}: {exc}")
                finally:
                    self._processing[user_id] = False
                    queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[Queue] Worker error for user {user_id}: {exc}")
                self._processing[user_id] = False

    def get_queue_size(self, user_id: int) -> int:
        if user_id not in self._queues:
            return 0
        return self._queues[user_id].qsize()

    def is_processing(self, user_id: int) -> bool:
        return self._processing.get(user_id, False)

    async def stop_all_workers(self):
        for worker in self._workers.values():
            if not worker.done():
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
        self._workers.clear()
        self._queues.clear()
        self._processing.clear()


queue_manager = UserQueueManager()
