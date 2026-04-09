from src.downloader import SERVICE_REGISTRY


def test_service_registry_contains_builtin_services():
    assert {"youtube", "tiktok", "instagram", "twitch", "pornhub", "spotify"}.issubset(SERVICE_REGISTRY.keys())
