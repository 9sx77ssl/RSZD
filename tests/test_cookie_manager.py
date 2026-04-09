from pathlib import Path

import pytest

from src.config import COOKIES_DIR
from src.cookie_manager import CookieImportError, get_cookie_path, import_cookie_file


def _clear_cookie_dir():
    for file in COOKIES_DIR.iterdir():
        if file.is_file() and file.name != ".gitkeep":
            file.unlink()


def test_import_cookie_file_splits_services(tmp_path: Path):
    _clear_cookie_dir()
    payload = tmp_path / "cookies.txt"
    payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\ttest-youtube\n"
        ".tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\ttest-tiktok\n",
        encoding="utf-8",
    )

    result = import_cookie_file(payload, "cookies.txt")

    assert result.total_lines == 2
    assert result.service_counts["youtube"] == 1
    assert result.service_counts["tiktok"] == 1
    assert Path(get_cookie_path("youtube")).exists()
    assert Path(get_cookie_path("tiktok")).exists()

    _clear_cookie_dir()


def test_import_cookie_file_merges_incremental_updates(tmp_path: Path):
    _clear_cookie_dir()
    first_payload = tmp_path / "cookies_part_1.txt"
    first_payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\told-sid\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tHSID\tkeep-this\n",
        encoding="utf-8",
    )

    second_payload = tmp_path / "cookies_part_2.txt"
    second_payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tnew-sid\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSSID\tadd-this\n",
        encoding="utf-8",
    )

    import_cookie_file(first_payload, "cookies_part_1.txt")
    result = import_cookie_file(second_payload, "cookies_part_2.txt")

    youtube_path = Path(get_cookie_path("youtube"))
    content = youtube_path.read_text(encoding="utf-8")

    assert result.service_counts["youtube"] == 3
    assert "\tSID\tnew-sid" in content
    assert "\tHSID\tkeep-this" in content
    assert "\tSSID\tadd-this" in content
    assert "\tSID\told-sid" not in content

    _clear_cookie_dir()


def test_import_cookie_file_updates_only_target_service(tmp_path: Path):
    _clear_cookie_dir()

    first_payload = tmp_path / "cookies_base.txt"
    first_payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tyoutube-stays\n"
        ".tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\ttiktok-stays\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tinsta-old\n",
        encoding="utf-8",
    )

    second_payload = tmp_path / "cookies_instagram_update.txt"
    second_payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tinsta-new\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tcsrftoken\tinsta-extra\n",
        encoding="utf-8",
    )

    import_cookie_file(first_payload, "cookies_base.txt")
    import_cookie_file(second_payload, "cookies_instagram_update.txt")

    youtube_content = Path(get_cookie_path("youtube")).read_text(encoding="utf-8")
    tiktok_content = Path(get_cookie_path("tiktok")).read_text(encoding="utf-8")
    instagram_content = Path(get_cookie_path("instagram")).read_text(encoding="utf-8")

    assert "\tSID\tyoutube-stays" in youtube_content
    assert "\tsessionid\ttiktok-stays" in tiktok_content
    assert "\tsessionid\tinsta-new" in instagram_content
    assert "\tcsrftoken\tinsta-extra" in instagram_content
    assert "\tsessionid\tinsta-old" not in instagram_content

    _clear_cookie_dir()


def test_import_cookie_file_rejects_unsupported_domains(tmp_path: Path):
    _clear_cookie_dir()

    payload = tmp_path / "cookies_invalid.txt"
    payload.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tTRUE\t0\tfoo\tbar\n",
        encoding="utf-8",
    )

    with pytest.raises(CookieImportError):
        import_cookie_file(payload, "cookies_invalid.txt")

    _clear_cookie_dir()
