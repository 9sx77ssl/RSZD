"""
Optional yt-dlp auto-updater.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from typing import Callable, Optional, Tuple

from config import AUTO_UPDATE_YTDLP, YTDLP_UPDATE_INTERVAL


class AutoUpdater:
    """Manages automatic yt-dlp updates."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_check: Optional[datetime] = None
        self._last_update: Optional[datetime] = None
        self._restart_callback: Optional[Callable[[], None]] = None

    def set_restart_callback(self, callback: Callable[[], None]):
        self._restart_callback = callback

    async def start(self):
        if not AUTO_UPDATE_YTDLP:
            print("[AutoUpdater] Disabled by configuration")
            return None
        self._running = True
        self._task = asyncio.create_task(self._update_loop())
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

    def _get_current_version(self) -> Optional[str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as exc:
            print(f"[AutoUpdater] Error getting version: {exc}")
        return None

    def _check_for_update(self) -> Tuple[bool, Optional[str]]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return False, None

            import json

            outdated = json.loads(result.stdout)
            for pkg in outdated:
                if pkg.get("name", "").lower() == "yt-dlp":
                    return True, pkg.get("latest_version")
            return False, None
        except Exception as exc:
            print(f"[AutoUpdater] Error checking for updates: {exc}")
            return False, None

    def _perform_update(self) -> bool:
        try:
            print("[AutoUpdater] Updating yt-dlp...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                self._last_update = datetime.now()
                print("[AutoUpdater] yt-dlp updated successfully")
                return True
            print(f"[AutoUpdater] Update failed: {result.stderr.strip()}")
            return False
        except Exception as exc:
            print(f"[AutoUpdater] Update error: {exc}")
            return False

    async def _update_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._check_and_update()
                await asyncio.sleep(YTDLP_UPDATE_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[AutoUpdater] Loop error: {exc}")
                await asyncio.sleep(60)

    async def _check_and_update(self):
        loop = asyncio.get_running_loop()
        current = await loop.run_in_executor(None, self._get_current_version)
        print(f"[AutoUpdater] Current yt-dlp version: {current}")
        self._last_check = datetime.now()
        update_available, new_version = await loop.run_in_executor(None, self._check_for_update)
        if not update_available:
            print("[AutoUpdater] yt-dlp is up to date")
            return

        print(f"[AutoUpdater] New version available: {new_version}")
        success = await loop.run_in_executor(None, self._perform_update)
        if not success:
            return

        updated = await loop.run_in_executor(None, self._get_current_version)
        print(f"[AutoUpdater] Updated to: {updated}")
        if self._restart_callback:
            print("[AutoUpdater] Requesting controlled restart")
            self._restart_callback()


auto_updater = AutoUpdater()


async def start_auto_updater(restart_callback: Optional[Callable[[], None]] = None):
    if restart_callback:
        auto_updater.set_restart_callback(restart_callback)
    return await auto_updater.start()


async def stop_auto_updater():
    await auto_updater.stop()
