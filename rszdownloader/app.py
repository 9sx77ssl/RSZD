"""
Telegram Media Downloader Bot - entry point.
"""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from rszdownloader.auto_updater import start_auto_updater, stop_auto_updater
from rszdownloader.cleaner import start_cleanup_task, stop_cleanup_task
from rszdownloader.config import BOT_TOKEN
from rszdownloader.db import db, init_db
from rszdownloader.handlers import router, set_bot
from rszdownloader.task_queue import queue_manager


_restart_requested = False
_restart_event: asyncio.Event | None = None
_main_loop: asyncio.AbstractEventLoop | None = None


def request_restart():
    """Request a controlled restart after background update."""
    global _restart_requested, _restart_event, _main_loop
    _restart_requested = True
    if _restart_event is not None and _main_loop is not None:
        _main_loop.call_soon_threadsafe(_restart_event.set)
    print("[Main] Restart requested")


async def on_startup():
    print("Bot starting...")
    await init_db()
    print("Database initialized")
    await start_cleanup_task(db)
    print("Cleanup task started")
    await start_auto_updater(restart_callback=request_restart)


async def on_shutdown():
    print("Bot shutting down...")
    await stop_auto_updater()
    await stop_cleanup_task()
    await queue_manager.stop_all_workers()
    await db.close()
    print("Shutdown complete")


async def main():
    global _restart_event, _main_loop
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable not set")
        print("Create a .env file or export BOT_TOKEN before starting the bot.")
        sys.exit(1)

    _restart_event = asyncio.Event()
    _main_loop = asyncio.get_running_loop()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    set_bot(bot)

    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    polling_task = asyncio.create_task(dp.start_polling(bot))
    restart_task = asyncio.create_task(_restart_event.wait())

    try:
        done, pending = await asyncio.wait({polling_task, restart_task}, return_when=asyncio.FIRST_COMPLETED)

        if restart_task in done and _restart_event.is_set():
            print("[Main] Restart event received, stopping polling")
            await dp.stop_polling()
            await polling_task

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        await bot.session.close()

    return _restart_requested


def run_bot():
    while True:
        try:
            restart = asyncio.run(main())
            if restart:
                print("[Main] Restarting bot after update...")
                continue
            break
        except KeyboardInterrupt:
            print("Bot stopped by user")
            break
        except Exception as exc:
            print(f"[Main] Fatal error: {exc}")
            print("[Main] Restarting in 5 seconds...")
            import time

            time.sleep(5)

