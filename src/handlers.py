"""Telegram message handlers using aiogram 3."""

from __future__ import annotations

import json
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import FSInputFile, InputMediaPhoto, KeyboardButton, Message, ReplyKeyboardMarkup

from src.config import ADMIN_IDS, BUTTON_START, COOKIES_DIR, MESSAGES, TELEGRAM_FILE_SIZE_LIMIT
from src.cookie_manager import CookieImportError, get_cookie_status_lines, import_cookie_file
from src.db import db
from src.downloader import (
    DownloadError,
    DownloadPackage,
    DurationExceededError,
    FileTooLargeError,
    UnsupportedUrlError,
    detect_service,
    download_media,
    extract_url,
    validate_url,
)
from src.task_queue import QueueTask, queue_manager


router = Router()
_bot: Bot | None = None


def get_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BUTTON_START)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def set_bot(bot: Bot):
    global _bot
    _bot = bot


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(MESSAGES["start"], parse_mode=ParseMode.HTML, reply_markup=get_keyboard())


@router.message(F.text == BUTTON_START)
async def btn_start(message: Message):
    await message.answer(MESSAGES["start"], parse_mode=ParseMode.HTML, reply_markup=get_keyboard())


@router.message(Command("cookies"))
async def cmd_cookies_status(message: Message):
    details = "\n".join(get_cookie_status_lines())
    await message.answer(MESSAGES["cookies_status"].format(details=details), parse_mode=ParseMode.HTML)


@router.message(F.document)
async def handle_document(message: Message, bot: Bot):
    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        return

    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.answer(MESSAGES["cookies_no_permission"], parse_mode=ParseMode.HTML)
        return

    temp_path = COOKIES_DIR / f"upload_{user_id}_{doc.file_unique_id}.txt"
    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, temp_path)
        result = import_cookie_file(temp_path, doc.file_name)
        services = ", ".join(f"{service} ({count})" for service, count in sorted(result.service_counts.items())) or "none"
        await message.answer(
            MESSAGES["cookies_updated"].format(
                filename=result.filename,
                lines=result.total_lines,
                services=services,
            ),
            parse_mode=ParseMode.HTML,
        )
        print(f"[Cookies] Updated by user {user_id}: {result.service_counts}")
    except CookieImportError as exc:
        await message.answer(MESSAGES["cookies_error"].format(reason=str(exc)), parse_mode=ParseMode.HTML)
    except Exception as exc:
        print(f"[Cookies] Error: {exc}")
        await message.answer(MESSAGES["cookies_error"].format(reason=str(exc)[:120]), parse_mode=ParseMode.HTML)
    finally:
        temp_path.unlink(missing_ok=True)


@router.message(F.text)
async def handle_message(message: Message, bot: Bot):
    url = extract_url(message.text)
    if not url:
        return

    if not validate_url(url):
        await message.answer(MESSAGES["error_unsupported"], parse_mode=ParseMode.HTML)
        return

    service = detect_service(url)
    if not service:
        await message.answer(MESSAGES["error_unsupported"], parse_mode=ParseMode.HTML)
        return

    if await db.has_active_task(message.from_user.id, url, service):
        await message.answer(MESSAGES["already_queued"], parse_mode=ParseMode.HTML)
        return

    status_msg = await message.answer(MESSAGES["processing"], parse_mode=ParseMode.HTML)
    task_id = await db.create_task(user_id=message.from_user.id, url=url, service=service)
    queue_task = QueueTask(
        task_id=task_id,
        user_id=message.from_user.id,
        url=url,
        service=service,
        message_id=status_msg.message_id,
        chat_id=message.chat.id,
    )

    queue_size = queue_manager.get_queue_size(message.from_user.id)
    is_processing = queue_manager.is_processing(message.from_user.id)
    await queue_manager.add_task(queue_task)

    if queue_size > 0 or is_processing:
        position = queue_size + (1 if is_processing else 0) + 1
        await db.update_task_status(task_id, "queued")
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=MESSAGES["queued"].format(position=position, total=position),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            print(f"[Handlers] Failed to edit queue status: {exc}")


def _cleanup_download_package(package: DownloadPackage | None):
    if not package:
        return
    if package.thumbnail:
        Path(package.thumbnail).unlink(missing_ok=True)


def _package_to_json(package: DownloadPackage) -> str:
    return json.dumps(
        {
            "files": package.files,
            "send_as": package.send_as,
            "title": package.title,
            "performer": package.performer,
            "thumbnail": package.thumbnail,
        }
    )


async def _send_package(bot: Bot, chat_id: int, package: DownloadPackage):
    if package.send_as == "audio":
        await bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(package.primary_path),
            title=package.title,
            performer=package.performer,
            thumbnail=FSInputFile(package.thumbnail) if package.thumbnail and Path(package.thumbnail).exists() else None,
        )
        return

    if package.send_as == "media_group":
        media = [
            InputMediaPhoto(media=FSInputFile(file_path))
            for index, file_path in enumerate(package.files)
        ]
        await bot.send_media_group(chat_id=chat_id, media=media)
        return

    await bot.send_video(
        chat_id=chat_id,
        video=FSInputFile(package.primary_path),
        thumbnail=FSInputFile(package.thumbnail) if package.thumbnail and Path(package.thumbnail).exists() else None,
        supports_streaming=True,
    )


async def process_task(task: QueueTask):
    global _bot
    if _bot is None:
        print("[Handlers] Bot not initialized")
        return

    chat_id = task.chat_id
    message_id = task.message_id
    package: DownloadPackage | None = None
    served_from_cache = False

    async def edit_status(text: str):
        try:
            await _bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            print(f"[Handlers] Failed to edit status for task {task.task_id}: {exc}")

    async def delete_status():
        try:
            await _bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            print(f"[Handlers] Failed to delete status for task {task.task_id}: {exc}")

    try:
        await db.update_task_status(task.task_id, "downloading")
        await edit_status(MESSAGES["downloading"])

        package = await db.get_cached_download(task.service, task.url)
        if package and all(Path(file_path).exists() for file_path in package.files):
            served_from_cache = True
            await edit_status(MESSAGES["served_from_cache"])
        else:
            package = await download_media(task.url, task.service)
            for file_path in package.files:
                if Path(file_path).exists() and Path(file_path).stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
                    raise FileTooLargeError("Payload file too large")
            await db.cache_download(task.service, task.url, package)

        await db.update_task_status(task.task_id, "downloaded", _package_to_json(package))
        if not served_from_cache:
            await edit_status(MESSAGES["sending"])
        await db.update_task_status(task.task_id, "sending")

        await _send_package(_bot, chat_id, package)

        await db.mark_task_sent(task.task_id)
        await delete_status()
        _cleanup_download_package(package)
    except DurationExceededError:
        await db.update_task_status(task.task_id, "error")
        await edit_status(MESSAGES["error_duration"])
        _cleanup_download_package(package)
    except FileTooLargeError:
        await db.update_task_status(task.task_id, "error")
        await edit_status(MESSAGES["error_file_size"])
        _cleanup_download_package(package)
    except (DownloadError, UnsupportedUrlError) as exc:
        print(f"[Handlers] Download error for task {task.task_id}: {exc}")
        await db.update_task_status(task.task_id, "error")
        await edit_status(MESSAGES["error_download"])
        _cleanup_download_package(package)
    except Exception as exc:
        print(f"[Handlers] Task error {task.task_id}: {exc}")
        await db.update_task_status(task.task_id, "error")
        await edit_status(MESSAGES["error_generic"].format(reason=str(exc)[:80]))
        _cleanup_download_package(package)


queue_manager.set_process_callback(process_task)
