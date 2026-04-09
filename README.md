# RSZDownloader

Telegram bot for downloading media from:

- TikTok videos and photo posts
- YouTube videos and Shorts
- Spotify tracks via YouTube audio extraction

The bot is built around `aiogram`, `yt-dlp`, SQLite, and a per-user FIFO queue so one user's downloads do not block everyone else.

## Features

- `.env`-based configuration
- Automatic `cookies.txt` import by sending the file directly to the bot
- Service-aware cookie storage for YouTube, TikTok, Spotify, and global fallback
- Per-user queue with progress messages
- Automatic cleanup of delivered files
- Optional `yt-dlp` auto-update with controlled restart
- Debian/Ubuntu-first installer with systemd setup

## Quick Start

1. Copy `.env.example` to `.env`
2. Fill `BOT_TOKEN`
3. Run:

```bash
sudo ./install.sh
```

The installer will:

- install system packages
- create a virtual environment
- install Python dependencies
- sync the project into `INSTALL_DIR`
- create and start a systemd service

## Configuration

Main variables in `.env`:

- `BOT_TOKEN`: Telegram bot token
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to upload cookies
- `DATABASE_PATH`: SQLite database path
- `DOWNLOAD_DIR`: temporary download directory
- `COOKIES_DIR`: service cookie storage directory
- `YOUTUBE_MAX_DURATION`: max YouTube duration in seconds
- `FILE_CLEANUP_DELAY`: delay before cleanup
- `AUTO_UPDATE_YTDLP`: `true` or `false`
- `SERVICE_NAME`: systemd service name
- `INSTALL_DIR`: deployment directory used by `install.sh`

## Cookies

To import cookies:

1. Export a `cookies.txt` file in Netscape format.
2. Send it to the bot as a normal Telegram document.

The bot will:

- validate the file
- split cookies by service domain
- store service-specific cookie files automatically

Use `/cookies` to inspect current cookie storage status.

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest
python main.py
```

## Operations

```bash
sudo systemctl status rsz-downloader
sudo journalctl -u rsz-downloader -f
sudo systemctl restart rsz-downloader
```

## Notes

- Official install support is Ubuntu/Debian.
- Runtime secrets are not committed; use `.env`.
- Downloaded files and imported cookies are gitignored.
