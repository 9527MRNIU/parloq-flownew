from __future__ import annotations

from app.config import get_settings


def test_management_origin_is_always_allowed_for_cookie_requests(monkeypatch) -> None:
    monkeypatch.setenv("MANAGEMENT_ORIGIN", "https://Customer.Example/")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://extra.example/,https://Customer.Example",
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.management_origin == "https://Customer.Example"
        assert settings.cors_origins == (
            "https://Customer.Example",
            "https://extra.example",
        )
    finally:
        get_settings.cache_clear()
