# RSZD

[![CI](https://github.com/9sx77ssl/RSZD/actions/workflows/ci.yml/badge.svg)](https://github.com/9sx77ssl/RSZD/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Minimal, fast, production-minded Telegram downloader bot built on `aiogram`, `yt-dlp`, SQLite, and a per-user queue.

## What It Supports

- TikTok videos
- TikTok photo posts and galleries
- Instagram Reels
- Instagram posts
- YouTube videos
- YouTube Shorts
- Spotify tracks through YouTube audio extraction

## Current Status

- CI is enabled on GitHub Actions for Python 3.11 and 3.12
- Runtime configuration is fully `.env` based
- Deployment uses a single `install.sh`
- File reuse cache avoids re-downloading the same URL again and again
- Cookie uploads work directly through Telegram as `cookies.txt`

## Repository Layout

```text
.
├── src/                  # application package
├── tests/                # automated tests
├── .github/workflows/    # CI
├── install.sh            # official installer
├── main.py               # thin runtime entrypoint
├── .env.example          # configuration template
└── pyproject.toml        # project metadata and pytest config
```

## Quick Start

1. Copy `.env.example` to `.env`
2. Set `BOT_TOKEN`
3. Run:

```bash
sudo ./install.sh
```

The installer:

- installs system packages
- creates a dedicated virtual environment
- installs Python dependencies into that venv
- syncs the project into `INSTALL_DIR`
- creates and starts a systemd service using `venv/bin/python`

## Configuration

Important `.env` keys:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_PATH`
- `DOWNLOAD_DIR`
- `COOKIES_DIR`
- `YOUTUBE_MAX_DURATION`
- `FILE_CLEANUP_DELAY`
- `AUTO_UPDATE_YTDLP`
- `SERVICE_NAME`
- `INSTALL_DIR`

## Cookies

To import cookies:

1. Export a Netscape-format `cookies.txt`
2. Send it to the bot as a normal Telegram document

Supported cookie formats:

- Recommended: Netscape `cookies.txt`
- Also accepted: JSON cookie array exports from browser tools

Best practice:

- export one full `cookies.txt`
- send it to the bot without renaming fields or editing it manually
- the bot will split and merge entries by service domain for YouTube, TikTok, and Instagram
- unsupported domains are ignored and a file with only unrelated cookies is rejected

Notes:

- Spotify cookies are not required in the current implementation
- Spotify downloads currently rely on YouTube matching and YouTube-side download access

The bot validates the file, splits cookies by service domain, and stores service-specific cookie files automatically. Use `/cookies` to inspect the current state.

Cookie behavior:

- the bot works without cookies too
- when cookies exist, it prefers them first
- if a request fails with cookies, supported download paths retry without cookies

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

- import smoke checks
- `python -m compileall main.py src tests`
- `bash -n install.sh`
- `python -m pytest`

## Architecture Notes

- `src/downloader.py` uses a typed service registry so new services can be added without turning the main flow into a large conditional block
- `src/db.py` stores a short-lived cache of downloaded files, which keeps repeat requests fast and reduces unnecessary source traffic
- `src/handlers.py` keeps chat output minimal and avoids extra message spam

## Good Next Services with yt-dlp

- X / Twitter video
- Twitch clips
- Reddit hosted video
- SoundCloud tracks
- Vimeo links

## Operations

```bash
sudo systemctl status rszd
sudo journalctl -u rszd -f
sudo systemctl restart rszd
```

## Notes

- Official installer support is Ubuntu and Debian
- Runtime secrets are never committed
- Downloads and imported cookies are gitignored
