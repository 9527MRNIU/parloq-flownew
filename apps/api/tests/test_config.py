from __future__ import annotations

from app.config import get_settings


def test_proxy_mock_does_not_inherit_bitly_mock(monkeypatch) -> None:
    monkeypatch.setenv("BITLY_MOCK", "true")
    monkeypatch.delenv("IP_PROXY_MOCK", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.bitly_mock is True
        assert settings.ip_proxy_mock is False
    finally:
        get_settings.cache_clear()


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
