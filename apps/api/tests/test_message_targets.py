from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.business_schemas import SendRequest


def test_send_request_accepts_phone_contact_jid_and_group_jid() -> None:
    common = {"message": "hello", "idempotencyKey": "message-target-test"}

    assert SendRequest(to="12025550123", **common).to == "+12025550123"
    assert (
        SendRequest(to="12025550123@s.whatsapp.net", **common).to
        == "12025550123@s.whatsapp.net"
    )
    assert (
        SendRequest(to="120363000000001@g.us", **common).to
        == "120363000000001@g.us"
    )


def test_send_request_rejects_unsupported_jids() -> None:
    with pytest.raises(ValidationError):
        SendRequest(
            to="not-a-group@g.us",
            message="hello",
            idempotencyKey="message-target-test",
        )
