# RSZDownloader

[![CI](https://github.com/9sx77ssl/RSZD/actions/workflows/ci.yml/badge.svg)](https://github.com/9sx77ssl/RSZD/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Production-minded Telegram downloader bot built on `aiogram`, `yt-dlp`, SQLite, and a per-user FIFO queue.

It currently supports:

- TikTok videos
- TikTok photo posts / galleries
- YouTube videos
- YouTube Shorts
- Spotify tracks via YouTube audio extraction

## Status

- CI: GitHub Actions validates imports, bytecode compilation, installer syntax, and tests on every push and pull request
- Runtime config: fully `.env`-driven
- Deployment: single `install.sh` flow for Ubuntu/Debian
- Cookies: direct `cookies.txt` upload through Telegram

## Repository Layout

```text
.
├── rszdownloader/         # main application package
├── tests/                 # automated tests
├── .github/workflows/     # CI pipelines
├── install.sh             # official installer
├── main.py                # thin executable wrapper
└── .env.example           # configuration template
```

## Features

- Clean package structure ready for extension
- Typed service registry for downloader backends
- Automatic service-aware cookie splitting
- Per-user queue with status updates
- Automatic cleanup of delivered files
- Optional controlled `yt-dlp` auto-update
- Systemd installation path for server use

## Quick Start

1. Copy `.env.example` to `.env`
2. Fill `BOT_TOKEN`
3. Run:

```bash
sudo ./install.sh
```

The installer will install system packages, create the virtual environment, sync the project into `INSTALL_DIR`, install dependencies, and create/start the systemd service.

## Configuration

Main variables in `.env`:

- `BOT_TOKEN`: Telegram bot token
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to upload cookies
- `DATABASE_PATH`: SQLite database path
- `DOWNLOAD_DIR`: temporary download directory
- `COOKIES_DIR`: service cookie storage directory
- `YOUTUBE_MAX_DURATION`: max YouTube duration in seconds
- `FILE_CLEANUP_DELAY`: delay before deleting delivered files
- `AUTO_UPDATE_YTDLP`: `true` or `false`
- `SERVICE_NAME`: systemd service name
- `INSTALL_DIR`: deployment directory used by `install.sh`

## Cookies

To import cookies:

1. Export a Netscape-format `cookies.txt`
2. Send it to the bot as a normal Telegram document

The bot validates the file, splits cookies by service domain, and stores service-specific cookie files automatically. Use `/cookies` to inspect current cookie storage status.

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m pytest
python main.py
```

## CI

The GitHub Actions pipeline runs:

- `python -m compileall .`
- `python -m pytest`
- import smoke checks
- `bash -n install.sh`

## Extending with yt-dlp

The downloader layer now uses a typed service registry, so adding a new provider is straightforward:

1. implement a new async download function returning `DownloadPackage`
2. register it in `SERVICE_REGISTRY`
3. extend hostname detection for the new service
4. add tests for URL detection and service behavior

Good next candidates for expansion with `yt-dlp`:

- Instagram Reels and posts
- X/Twitter videos
- Twitch clips
- Reddit hosted video
- SoundCloud tracks

## Operations

```bash
sudo systemctl status rsz-downloader
sudo journalctl -u rsz-downloader -f
sudo systemctl restart rsz-downloader
```

## Notes

- Official install support is Ubuntu/Debian
- Runtime secrets are not committed
- Downloaded files and imported cookies are gitignored
