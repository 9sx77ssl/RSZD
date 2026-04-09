"""Application configuration loaded from environment variables and .env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def _load_dotenv() -> None:
    """Load a local .env file without overriding exported environment values."""
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer value for {name}: {value}") from exc


def _get_csv_ints(name: str) -> List[int]:
    raw = os.getenv(name, "")
    values: List[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError as exc:
            raise RuntimeError(f"Invalid integer in {name}: {item}") from exc
    return values


def _resolve_path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: List[int]
    database_path: Path
    download_dir: Path
    cookies_dir: Path
    log_level: str
    youtube_max_duration: int
    file_cleanup_delay: int
    cleanup_interval: int
    yt_dlp_update_interval: int
    auto_update_ytdlp: bool
    telegram_file_size_limit: int
    cookie_auto_import: bool
    service_name: str
    install_dir: str


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = _get_csv_ints("ADMIN_IDS")

DATABASE_PATH = _resolve_path("DATABASE_PATH", "bot.db")
DOWNLOAD_DIR = _resolve_path("DOWNLOAD_DIR", "downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

COOKIES_DIR = _resolve_path("COOKIES_DIR", "cookies")
COOKIES_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
YOUTUBE_MAX_DURATION = _get_int("YOUTUBE_MAX_DURATION", 15 * 60)
FILE_CLEANUP_DELAY = _get_int("FILE_CLEANUP_DELAY", 15 * 60)
CLEANUP_INTERVAL = _get_int("CLEANUP_INTERVAL", 60)
YTDLP_UPDATE_INTERVAL = _get_int("YTDLP_UPDATE_INTERVAL", 6 * 60 * 60)
AUTO_UPDATE_YTDLP = _get_bool("AUTO_UPDATE_YTDLP", False)
TELEGRAM_FILE_SIZE_LIMIT = _get_int("TELEGRAM_FILE_SIZE_LIMIT", 50 * 1024 * 1024)
COOKIE_AUTO_IMPORT = _get_bool("COOKIE_AUTO_IMPORT", True)
SERVICE_NAME = os.getenv("SERVICE_NAME", "rszd").strip() or "rszd"
INSTALL_DIR = os.getenv("INSTALL_DIR", str(PROJECT_DIR)).strip() or str(PROJECT_DIR)

if YOUTUBE_MAX_DURATION <= 0:
    raise RuntimeError("YOUTUBE_MAX_DURATION must be positive")
if FILE_CLEANUP_DELAY < 0:
    raise RuntimeError("FILE_CLEANUP_DELAY must be non-negative")
if CLEANUP_INTERVAL <= 0:
    raise RuntimeError("CLEANUP_INTERVAL must be positive")
if TELEGRAM_FILE_SIZE_LIMIT <= 0:
    raise RuntimeError("TELEGRAM_FILE_SIZE_LIMIT must be positive")


SETTINGS = Settings(
    bot_token=BOT_TOKEN,
    admin_ids=ADMIN_IDS,
    database_path=DATABASE_PATH,
    download_dir=DOWNLOAD_DIR,
    cookies_dir=COOKIES_DIR,
    log_level=LOG_LEVEL,
    youtube_max_duration=YOUTUBE_MAX_DURATION,
    file_cleanup_delay=FILE_CLEANUP_DELAY,
    cleanup_interval=CLEANUP_INTERVAL,
    yt_dlp_update_interval=YTDLP_UPDATE_INTERVAL,
    auto_update_ytdlp=AUTO_UPDATE_YTDLP,
    telegram_file_size_limit=TELEGRAM_FILE_SIZE_LIMIT,
    cookie_auto_import=COOKIE_AUTO_IMPORT,
    service_name=SERVICE_NAME,
    install_dir=INSTALL_DIR,
)


COOKIE_SERVICE_DOMAINS: Dict[str, tuple[str, ...]] = {
    "youtube": (".youtube.com", "youtube.com", ".google.com", "google.com", ".youtu.be", "youtu.be"),
    "tiktok": (".tiktok.com", "tiktok.com", ".www.tiktok.com", "www.tiktok.com", ".vm.tiktok.com", "vm.tiktok.com"),
    "instagram": (".instagram.com", "instagram.com", ".www.instagram.com", "www.instagram.com"),
    "spotify": (".spotify.com", "spotify.com", ".open.spotify.com", "open.spotify.com"),
}

COOKIE_FILENAMES: Dict[str, str] = {
    "youtube": "youtube.cookies.txt",
    "tiktok": "tiktok.cookies.txt",
    "instagram": "instagram.cookies.txt",
    "spotify": "spotify.cookies.txt",
    "global": "global.cookies.txt",
}

MESSAGES = {
    "start": (
        "<b>RSZD</b>\n"
        "<blockquote>Clean downloads for TikTok, Instagram, YouTube, Shorts, and Spotify.</blockquote>\n\n"
        "Send a link and the bot will handle the rest.\n"
        "Admins can upload <code>cookies.txt</code> directly when needed."
    ),
    "processing": "<b>Preparing request</b>\n<blockquote>Please wait.</blockquote>",
    "queued": "<b>Queued</b>\n<blockquote>Position {position} of {total}</blockquote>",
    "already_queued": "<b>Already queued</b>\n<blockquote>This link is already being processed.</blockquote>",
    "downloading": "<b>Downloading</b>\n<blockquote>Fetching the media now.</blockquote>",
    "sending": "<b>Sending</b>\n<blockquote>Uploading the result.</blockquote>",
    "served_from_cache": "<b>Ready instantly</b>\n<blockquote>Reused a recent download.</blockquote>",
    "error_unsupported": "<b>Request rejected</b>\n<blockquote>This link is not supported.</blockquote>",
    "error_duration": "<b>Too long</b>\n<blockquote>This YouTube video is above the configured duration limit.</blockquote>",
    "error_download": "<b>Download failed</b>\n<blockquote>The source could not be downloaded right now.</blockquote>",
    "error_file_size": "<b>Too large</b>\n<blockquote>The file is above the Telegram size limit.</blockquote>",
    "error_generic": "<b>Operation failed</b>\n<blockquote>{reason}</blockquote>",
    "cookies_updated": (
        "<b>Cookies imported</b>\n"
        "<blockquote>File: <code>{filename}</code>\n"
        "Entries: {lines}\n"
        "Targets: {services}</blockquote>"
    ),
    "cookies_error": "<b>Cookie import failed</b>\n<blockquote>{reason}</blockquote>",
    "cookies_status": "<b>Cookie status</b>\n<blockquote>{details}</blockquote>",
    "cookies_no_permission": "<b>Access denied</b>\n<blockquote>You are not allowed to upload cookies.</blockquote>",
}

BUTTON_START = "Start"
