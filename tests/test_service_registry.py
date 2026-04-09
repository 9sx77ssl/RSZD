from rszdownloader.downloader import SERVICE_REGISTRY


def test_service_registry_contains_builtin_services():
    assert {"youtube", "tiktok", "spotify"}.issubset(SERVICE_REGISTRY.keys())
