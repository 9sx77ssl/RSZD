import json
from pathlib import Path

import pytest

from src.db import Database
from src.downloader import DownloadPackage


@pytest.mark.asyncio
async def test_cached_download_roundtrip(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    payload = tmp_path / "video.mp4"
    payload.write_bytes(b"video")

    package = DownloadPackage(files=[str(payload)], send_as="video", title="Sample")
    await db.cache_download("youtube", "https://youtu.be/example", package)

    cached = await db.get_cached_download("youtube", "https://youtu.be/example")

    assert cached is not None
    assert cached.files == [str(payload)]
    assert cached.send_as == "video"
    assert cached.title == "Sample"

    await db.close()


@pytest.mark.asyncio
async def test_active_task_detection(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    task_id = await db.create_task(1, "https://youtu.be/example", "youtube")

    assert await db.has_active_task(1, "https://youtu.be/example", "youtube") is True

    await db.mark_task_sent(task_id)

    assert await db.has_active_task(1, "https://youtu.be/example", "youtube") is False

    await db.close()
