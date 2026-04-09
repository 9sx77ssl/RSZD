from pathlib import Path

from src.config import COOKIES_DIR
from src.cookie_manager import get_cookie_path, import_cookie_file


def test_import_cookie_file_splits_services(tmp_path: Path):
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

    for file in COOKIES_DIR.iterdir():
        if file.is_file() and file.name != ".gitkeep":
            file.unlink()
