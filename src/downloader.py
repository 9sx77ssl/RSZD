"""
Media download logic using yt-dlp.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, TypedDict
from urllib.parse import urlparse

import yt_dlp

from src.config import DOWNLOAD_DIR, TELEGRAM_FILE_SIZE_LIMIT, YOUTUBE_MAX_DURATION
from src.cookie_manager import get_cookie_path


class DownloadError(Exception):
    pass


class DurationExceededError(Exception):
    pass


class UnsupportedUrlError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


@dataclass
class DownloadPackage:
    files: list[str]
    send_as: Literal["audio", "video", "media_group"]
    title: str
    performer: Optional[str] = None
    thumbnail: Optional[str] = None

    @property
    def primary_path(self) -> str:
        return self.files[0]


URL_REGEX = re.compile(r"https?://[^\s<>{}\"|\\^`\[\]]+")

ServiceName = Literal["youtube", "tiktok", "instagram", "twitch", "pornhub", "spotify"]

SERVICE_HOSTS: dict[ServiceName, set[str]] = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"},
    "tiktok": {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "twitch": {"clips.twitch.tv"},
    "pornhub": {"pornhub.com", "www.pornhub.com"},
    "spotify": {"open.spotify.com"},
}

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".webm", ".opus"}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
_ua_index = 0


def extract_url(text: str) -> Optional[str]:
    match = URL_REGEX.search(text or "")
    return match.group(0) if match else None


def _normalized_host(url: str) -> Optional[str]:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            return host
        return host
    except Exception:
        return None


def detect_service(url: str) -> Optional[ServiceName]:
    host = _normalized_host(url)
    if not host:
        return None
    path = urlparse(url).path or ""
    if host == "clips.twitch.tv" or (host in {"twitch.tv", "www.twitch.tv"} and "/clip/" in path):
        return "twitch"
    for service, allowed_hosts in SERVICE_HOSTS.items():
        for allowed in allowed_hosts:
            if host == allowed or host.endswith(f".{allowed}"):
                return service
    return None


class SpotifyMetadata(TypedDict):
    title: Optional[str]
    thumbnail_url: Optional[str]


@dataclass(frozen=True)
class ServiceHandler:
    name: ServiceName
    download: Callable[[str], Awaitable[DownloadPackage]]


SERVICE_REGISTRY: dict[ServiceName, ServiceHandler] = {}


def register_service(handler: ServiceHandler) -> None:
    SERVICE_REGISTRY[handler.name] = handler


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username or parsed.password:
            return False
        host = parsed.hostname
        if not host:
            return False
        lowered = host.lower().rstrip(".")
        try:
            ip = ipaddress.ip_address(lowered)
            if any([ip.is_private, ip.is_loopback, ip.is_multicast, ip.is_reserved, ip.is_link_local]):
                return False
        except ValueError:
            if lowered in {"localhost"}:
                return False
        if ".." in parsed.path:
            return False
        return detect_service(url) is not None
    except Exception:
        return False


def _next_user_agent() -> str:
    global _ua_index
    user_agent = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return user_agent


def sanitize_filename(title: str, service: str, extension: str, index: Optional[int] = None) -> str:
    safe_title = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", title or "")
    safe_title = re.sub(r"\s+", "_", safe_title).strip("._")
    safe_title = safe_title[:80] or "media"
    suffix = f"_{index}" if index is not None else ""
    return f"{service}_{safe_title}{suffix}.{extension}"


class QuietLogger:
    def debug(self, msg):  # noqa: D401
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        print(f"[yt-dlp] {msg}")


def get_base_opts(service: str, use_cookies: bool = True, source_address: Optional[str] = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": QuietLogger(),
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "http_headers": {
            "User-Agent": _next_user_agent(),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if source_address:
        opts["source_address"] = source_address
    if use_cookies:
        cookie_path = get_cookie_path(service)
        if cookie_path:
            opts["cookiefile"] = cookie_path
    return opts


def _cookie_attempts(service: ServiceName) -> list[bool]:
    return [True, False] if get_cookie_path(service) else [False]


def is_retryable_error(error_str: str) -> bool:
    error_lower = error_str.lower()
    return any(token in error_lower for token in ("403", "429", "rate", "too many", "temporary", "timeout", "connection"))


def is_permanent_error(error_str: str) -> bool:
    error_lower = error_str.lower()
    return any(token in error_lower for token in ("private", "removed", "unavailable", "not exist", "deleted", "copyright", "blocked"))


def _collect_downloads(prefix: str) -> list[Path]:
    return sorted(path for path in DOWNLOAD_DIR.glob(f"{prefix}*") if path.is_file())


def _rename_file(path: Path, service: str, title: str, index: Optional[int] = None) -> Path:
    ext = path.suffix.lstrip(".") or "bin"
    destination = DOWNLOAD_DIR / sanitize_filename(title, service, ext, index=index)
    if destination.exists():
        destination.unlink()
    path.rename(destination)
    return destination


def _delete_paths(paths: list[Path]):
    for path in paths:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def _is_tiktok_photo_url(url: str) -> bool:
    parsed = urlparse(url)
    return "/photo/" in (parsed.path or "")


async def _extract_info_with_fallback(service: ServiceName, url: str, extra_opts: Optional[dict] = None) -> dict:
    loop = asyncio.get_running_loop()

    def _get_info():
        for use_cookies in _cookie_attempts(service):
            try:
                opts = {**get_base_opts(service, use_cookies=use_cookies), **(extra_opts or {})}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception:
                continue
        raise DownloadError(f"{service.capitalize()}: could not fetch media metadata")

    return await loop.run_in_executor(None, _get_info)


async def _download_single_video_service(
    service: ServiceName,
    url: str,
    *,
    output_prefix: str,
    title: str,
    info_opts: Optional[dict] = None,
    download_opts: Optional[dict] = None,
) -> DownloadPackage:
    loop = asyncio.get_running_loop()
    info = await _extract_info_with_fallback(service, url, info_opts)
    media_id = info.get("id", output_prefix)
    title = info.get("title") or title

    def _download():
        last_error = None
        attempts = [(use_cookies, None) for use_cookies in _cookie_attempts(service)]
        attempts.append((False, "0.0.0.0"))
        for use_cookies, source_address in attempts:
            try:
                _delete_paths(_collect_downloads(media_id))
                opts = {
                    **get_base_opts(service, use_cookies=use_cookies, source_address=source_address),
                    "outtmpl": str(DOWNLOAD_DIR / f"{media_id}.%(ext)s"),
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                    "remux_video": "mp4",
                    "format_sort": ["ext:mp4", "vcodec:h264", "acodec:aac"],
                    "noplaylist": True,
                    "writethumbnail": True,
                    **(download_opts or {}),
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                files = _collect_downloads(media_id)
                if files:
                    return files, title
            except Exception as exc:
                last_error = str(exc)
                print(f"[{service.capitalize()}] Download attempt failed: {last_error[:120]}")
                if last_error and is_permanent_error(last_error):
                    break
        raise DownloadError(f"{service.capitalize()}: {last_error or 'download failed'}")

    raw_files, resolved_title = await loop.run_in_executor(None, _download)
    video_files = [path for path in raw_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    image_files = [path for path in raw_files if path.suffix.lower() in IMAGE_EXTENSIONS]
    other_files = [path for path in raw_files if path not in video_files + image_files]

    if not video_files:
        _delete_paths(raw_files)
        raise DownloadError(f"{service.capitalize()}: output file not found")

    video_path = max(video_files, key=lambda item: item.stat().st_size)
    thumbnail = image_files[0] if image_files else None
    renamed_video = _rename_file(video_path, service, resolved_title)
    renamed_thumbnail = _rename_file(thumbnail, f"{service}_thumb", resolved_title) if thumbnail else None
    _delete_paths([path for path in video_files if path != video_path] + [path for path in image_files if path != thumbnail] + other_files)

    if renamed_video.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
        renamed_video.unlink(missing_ok=True)
        if renamed_thumbnail:
            renamed_thumbnail.unlink(missing_ok=True)
        raise FileTooLargeError("File exceeds Telegram size limit")

    return DownloadPackage(
        files=[str(renamed_video)],
        send_as="video",
        title=resolved_title,
        thumbnail=str(renamed_thumbnail) if renamed_thumbnail else None,
    )


async def download_tiktok(url: str) -> DownloadPackage:
    print("[TikTok] Fetching post metadata...")
    loop = asyncio.get_running_loop()
    info = await _extract_info_with_fallback("tiktok", url)
    post_id = info.get("id", "tiktok")
    title = info.get("title") or "tiktok_post"
    has_gallery = bool(info.get("entries")) or info.get("_type") in {"playlist", "multi_video"}

    def _download():
        ydl_opts = {
            **get_base_opts("tiktok"),
            "outtmpl": str(DOWNLOAD_DIR / (f"{post_id}_%(autonumber)s.%(ext)s" if has_gallery else f"{post_id}.%(ext)s")),
            "noplaylist": not has_gallery,
            "writethumbnail": False,
            "remux_video": "mp4",
            "format_sort": ["ext:mp4", "vcodec:h264", "acodec:aac"],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        return _collect_downloads(post_id)

    raw_files = await loop.run_in_executor(None, _download)
    if not raw_files:
        raise DownloadError("TikTok: файлы не были скачаны")

    image_files = [path for path in raw_files if path.suffix.lower() in IMAGE_EXTENSIONS]
    video_files = [path for path in raw_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    other_files = [path for path in raw_files if path not in image_files + video_files]

    if image_files:
        renamed = [_rename_file(path, "tiktok", title, index=index + 1) for index, path in enumerate(image_files)]
        _delete_paths(video_files + other_files)
        for path in renamed:
            if path.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
                _delete_paths(renamed)
                raise FileTooLargeError("TikTok photo exceeds Telegram size limit")
        return DownloadPackage(
            files=[str(path) for path in renamed],
            send_as="media_group",
            title=title,
        )

    if not video_files:
        _delete_paths(other_files)
        raise DownloadError("TikTok: не найдено поддерживаемое медиа")

    video_path = max(video_files, key=lambda item: item.stat().st_size)
    renamed_video = _rename_file(video_path, "tiktok", title)
    _delete_paths([path for path in video_files if path != video_path] + other_files)
    if renamed_video.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
        renamed_video.unlink(missing_ok=True)
        raise FileTooLargeError("TikTok video exceeds Telegram size limit")

    return DownloadPackage(files=[str(renamed_video)], send_as="video", title=title)


async def download_instagram(url: str) -> DownloadPackage:
    print("[Instagram] Fetching post metadata...")
    loop = asyncio.get_running_loop()
    info = await _extract_info_with_fallback("instagram", url)
    post_id = info.get("id", "instagram")
    title = info.get("title") or info.get("description") or "instagram_post"
    has_gallery = bool(info.get("entries")) or info.get("_type") in {"playlist", "multi_video"}

    def _download():
        ydl_opts = {
            **get_base_opts("instagram"),
            "outtmpl": str(DOWNLOAD_DIR / (f"{post_id}_%(autonumber)s.%(ext)s" if has_gallery else f"{post_id}.%(ext)s")),
            "noplaylist": not has_gallery,
            "writethumbnail": False,
            "remux_video": "mp4",
            "format_sort": ["ext:mp4", "vcodec:h264", "acodec:aac"],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        return _collect_downloads(post_id)

    raw_files = await loop.run_in_executor(None, _download)
    if not raw_files:
        raise DownloadError("Instagram: media files were not downloaded")

    image_files = [path for path in raw_files if path.suffix.lower() in IMAGE_EXTENSIONS]
    video_files = [path for path in raw_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    other_files = [path for path in raw_files if path not in image_files + video_files]

    if image_files and not video_files:
        renamed = [_rename_file(path, "instagram", title, index=index + 1) for index, path in enumerate(image_files)]
        _delete_paths(other_files)
        for path in renamed:
            if path.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
                _delete_paths(renamed)
                raise FileTooLargeError("Instagram image exceeds Telegram size limit")
        return DownloadPackage(files=[str(path) for path in renamed], send_as="media_group", title=title)

    if not video_files:
        _delete_paths(other_files)
        raise DownloadError("Instagram: supported media was not found")

    video_path = max(video_files, key=lambda item: item.stat().st_size)
    renamed_video = _rename_file(video_path, "instagram", title)
    _delete_paths([path for path in video_files if path != video_path] + image_files + other_files)
    if renamed_video.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
        renamed_video.unlink(missing_ok=True)
        raise FileTooLargeError("Instagram video exceeds Telegram size limit")

    return DownloadPackage(files=[str(renamed_video)], send_as="video", title=title)


async def download_youtube(url: str) -> DownloadPackage:
    print("[YouTube] Checking video...")
    loop = asyncio.get_running_loop()
    info = await _extract_info_with_fallback("youtube", url, {"noplaylist": True})
    duration = info.get("duration") or 0
    if duration > YOUTUBE_MAX_DURATION:
        raise DurationExceededError(f"Video is {duration} seconds")

    video_id = info.get("id", "youtube")
    title = info.get("title") or "youtube_video"

    def _download():
        last_error = None
        for use_cookies, source_address in ((True, None), (False, None), (False, "0.0.0.0")):
            try:
                _delete_paths(_collect_downloads(video_id))
                ydl_opts = {
                    **get_base_opts("youtube", use_cookies=use_cookies, source_address=source_address),
                    "outtmpl": str(DOWNLOAD_DIR / f"{video_id}.%(ext)s"),
                    "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
                    "merge_output_format": "mp4",
                    "noplaylist": True,
                    "writethumbnail": True,
                    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                files = _collect_downloads(video_id)
                if files:
                    return files
            except Exception as exc:
                last_error = str(exc)
                print(f"[YouTube] Download attempt failed: {last_error[:120]}")
                if last_error and is_permanent_error(last_error):
                    raise DownloadError("Видео недоступно или приватное")
                if last_error and not is_retryable_error(last_error):
                    continue
        raise DownloadError(f"YouTube: {last_error or 'не удалось скачать видео'}")

    raw_files = await loop.run_in_executor(None, _download)
    video_files = [path for path in raw_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    image_files = [path for path in raw_files if path.suffix.lower() in IMAGE_EXTENSIONS]
    other_files = [path for path in raw_files if path not in video_files + image_files]

    if not video_files:
        _delete_paths(raw_files)
        raise DownloadError("YouTube: выходной файл не найден")

    video_path = max(video_files, key=lambda item: item.stat().st_size)
    thumbnail = image_files[0] if image_files else None
    renamed_video = _rename_file(video_path, "youtube", title)
    renamed_thumbnail = _rename_file(thumbnail, "youtube_thumb", title) if thumbnail else None
    _delete_paths([path for path in video_files if path != video_path] + [path for path in image_files if path != thumbnail] + other_files)

    if renamed_video.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
        renamed_video.unlink(missing_ok=True)
        if renamed_thumbnail:
            renamed_thumbnail.unlink(missing_ok=True)
        raise FileTooLargeError("File exceeds Telegram size limit")

    return DownloadPackage(
        files=[str(renamed_video)],
        send_as="video",
        title=title,
        thumbnail=str(renamed_thumbnail) if renamed_thumbnail else None,
    )


def _fetch_spotify_metadata(url: str) -> SpotifyMetadata:
    result: SpotifyMetadata = {"title": None, "thumbnail_url": None}
    try:
        oembed_url = f"https://open.spotify.com/oembed?url={url}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": _next_user_agent()})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            result["title"] = data.get("title")
            result["thumbnail_url"] = data.get("thumbnail_url")
    except Exception:
        pass
    return result


def _score_candidate(candidate: Dict[str, Any], full_title: str) -> int:
    title = candidate.get("title", "").lower()
    score = 0
    wanted_tokens = [token for token in re.split(r"\W+", full_title.lower()) if len(token) > 2]
    if not wanted_tokens:
        return score
    matches = sum(1 for token in wanted_tokens if token in title)
    score += matches * 10
    if "official" in title:
        score += 8
    if "topic" in (candidate.get("channel") or "").lower():
        score += 12
    if any(bad in title for bad in ("remix", "slowed", "reverb", "karaoke", "cover", "nightcore", "sped up")):
        score -= 25
    duration = candidate.get("duration")
    if duration and 60 <= duration <= 720:
        score += 5
    return score


async def download_spotify(url: str) -> DownloadPackage:
    print("[Spotify] Fetching track metadata...")
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, _fetch_spotify_metadata, url)
    full_title = meta.get("title")
    if not full_title:
        raise DownloadError("Не удалось получить название трека Spotify")

    thumbnail_url = meta.get("thumbnail_url")
    search_queries = [f"ytsearch5:{full_title}", f"ytsearch5:{full_title} official audio"]

    def _find_candidates():
        candidates = []
        for query in search_queries:
            with yt_dlp.YoutubeDL({**get_base_opts("youtube"), "extract_flat": "in_playlist", "default_search": "ytsearch"}) as ydl:
                results = ydl.extract_info(query, download=False)
                for entry in results.get("entries", []) if results else []:
                    if entry and entry.get("url"):
                        candidates.append(entry)
        unique = {}
        for item in candidates:
            unique[item["url"]] = item
        ranked = sorted(unique.values(), key=lambda item: _score_candidate(item, full_title), reverse=True)
        return ranked[:5]

    candidates = await loop.run_in_executor(None, _find_candidates)
    if not candidates:
        raise DownloadError("Трек не найден на YouTube")

    track_id_match = re.search(r"track/([a-zA-Z0-9]+)", url)
    track_id = track_id_match.group(1) if track_id_match else "spotify"

    def _download_audio():
        last_error = None
        for candidate in candidates:
            for use_cookies in _cookie_attempts("youtube"):
                try:
                    _delete_paths(_collect_downloads(f"spotify_{track_id}"))
                    ydl_opts = {
                        **get_base_opts("youtube", use_cookies=use_cookies),
                        "outtmpl": str(DOWNLOAD_DIR / f"spotify_{track_id}.%(ext)s"),
                        "format": "bestaudio/best",
                        "noplaylist": True,
                        "postprocessors": [
                            {
                                "key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "192",
                            }
                        ],
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([candidate["url"]])
                    files = _collect_downloads(f"spotify_{track_id}")
                    mp3_files = [path for path in files if path.suffix.lower() == ".mp3"]
                    if mp3_files:
                        return mp3_files[0]
                except Exception as exc:
                    last_error = str(exc)
                    print(f"[Spotify] Candidate failed: {last_error[:120]}")
                    if last_error and is_permanent_error(last_error):
                        break
        raise DownloadError(f"Spotify: {last_error or 'не удалось скачать трек'}")

    audio_path = await loop.run_in_executor(None, _download_audio)
    if audio_path.stat().st_size > TELEGRAM_FILE_SIZE_LIMIT:
        audio_path.unlink(missing_ok=True)
        raise FileTooLargeError("Audio exceeds Telegram size limit")

    renamed_audio = _rename_file(audio_path, "spotify", full_title)

    thumb_path = None
    if thumbnail_url:
        thumb_path = DOWNLOAD_DIR / f"spotify_thumb_{track_id}.jpg"

        def _download_thumb():
            urllib.request.urlretrieve(thumbnail_url, thumb_path)

        try:
            await loop.run_in_executor(None, _download_thumb)
        except Exception:
            thumb_path = None

    performer = None
    track_title = full_title
    if " - " in full_title:
        track_title, performer = [part.strip() for part in full_title.rsplit(" - ", 1)]

    return DownloadPackage(
        files=[str(renamed_audio)],
        send_as="audio",
        title=track_title,
        performer=performer,
        thumbnail=str(thumb_path) if thumb_path and thumb_path.exists() else None,
    )


async def download_twitch_clip(url: str) -> DownloadPackage:
    print("[Twitch] Fetching clip...")
    return await _download_single_video_service(
        "twitch",
        url,
        output_prefix="twitch",
        title="twitch_clip",
    )


async def download_pornhub(url: str) -> DownloadPackage:
    print("[PornHub] Fetching video...")
    return await _download_single_video_service(
        "pornhub",
        url,
        output_prefix="pornhub",
        title="pornhub_video",
    )


register_service(ServiceHandler(name="tiktok", download=download_tiktok))
register_service(ServiceHandler(name="instagram", download=download_instagram))
register_service(ServiceHandler(name="twitch", download=download_twitch_clip))
register_service(ServiceHandler(name="pornhub", download=download_pornhub))
register_service(ServiceHandler(name="youtube", download=download_youtube))
register_service(ServiceHandler(name="spotify", download=download_spotify))


async def download_media(url: str, service: str) -> DownloadPackage:
    if service == "tiktok" and _is_tiktok_photo_url(url):
        raise DownloadError(
            "TikTok photo posts are currently limited by TikTok web access. "
            "Standard TikTok videos still work normally."
        )
    handler = SERVICE_REGISTRY.get(service)  # type: ignore[arg-type]
    if handler:
        return await handler.download(url)
    raise UnsupportedUrlError(f"Service '{service}' not supported")
