from src.downloader import detect_service, extract_url, validate_url


def test_extract_url():
    assert extract_url("hello https://youtube.com/watch?v=123 world") == "https://youtube.com/watch?v=123"


def test_detect_service_variants():
    assert detect_service("https://www.youtube.com/shorts/abc123") == "youtube"
    assert detect_service("https://vm.tiktok.com/abc") == "tiktok"
    assert detect_service("https://www.instagram.com/reel/C12345/") == "instagram"
    assert detect_service("https://open.spotify.com/track/123") == "spotify"


def test_validate_url_rejects_fake_host():
    assert not validate_url("https://youtube.com.evil.example/watch?v=1")
    assert not validate_url("http://127.0.0.1/test")
    assert validate_url("https://youtu.be/abc123")
