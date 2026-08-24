from __future__ import annotations

import hashlib
from pathlib import Path

from app.validation import phone_country_code


def test_phone_country_code_uses_numbering_plan_metadata() -> None:
    assert phone_country_code("+86 131 8707 1551") == "CN"
    assert phone_country_code("+49 151 23456789") == "DE"
    assert phone_country_code("+1 202 555 1001") == "US"
    assert phone_country_code("+7 777 123 4567") == "KZ"
    assert phone_country_code("+800 1234 5678") is None
    assert phone_country_code(None) is None


def test_vendored_phonenumberslite_wheel_checksum() -> None:
    wheel = (
        Path(__file__).resolve().parents[1]
        / "vendor"
        / "phonenumberslite"
        / "phonenumberslite-9.0.34-py2.py3-none-any.whl"
    )
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == (
        "cdf6be12d052c3de7921b9290b9f1ad93f18224d5be97b482f16327d03841828"
    )
