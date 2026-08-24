from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.security import utcnow


_UNSET = object()
_HTTP_CLIENT = httpx.Client(
    limits=httpx.Limits(max_connections=500, max_keepalive_connections=200),
    # On-demand sends may first warm a saved Baileys session. The gateway's
    # connect deadline is 45 seconds, so the control-plane read timeout must
    # leave room for that handshake while retaining a short TCP connect limit.
    timeout=httpx.Timeout(60.0, connect=5.0),
)


class GatewayError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        failure_detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.failure_detail = dict(failure_detail or {})


class WaGatewayClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.http_client = http_client or _HTTP_CLIENT

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if self.settings.wa_gateway_mock:
            return {}
        headers = {}
        if self.settings.wa_gateway_api_token:
            headers["Authorization"] = f"Bearer {self.settings.wa_gateway_api_token}"
        try:
            # httpx.Client is thread-safe.  Reusing it is critical for the task
            # worker: bursts do not create one TCP/TLS connection per message.
            response = self.http_client.request(
                method,
                f"{self.settings.wa_gateway_url}{path}",
                json=payload if payload is not None else None,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise GatewayError("WhatsApp 网关不可用") from exc
        if not response.is_success:
            failure_detail: dict[str, Any] = {}
            try:
                response_value = response.json()
            except (ValueError, TypeError):
                response_value = {}
            if isinstance(response_value, dict):
                error_value = response_value.get("error")
                if isinstance(error_value, dict) and isinstance(
                    error_value.get("failure"), dict
                ):
                    from app.services.pairing_observability import (
                        normalize_pairing_failure_detail,
                    )

                    failure_detail = normalize_pairing_failure_detail(
                        error_value["failure"]
                    )
            raise GatewayError(
                f"WhatsApp 网关请求失败（{response.status_code}）",
                status_code=response.status_code,
                failure_detail=failure_detail,
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise GatewayError("WhatsApp 网关返回无法识别的数据") from exc
        if not isinstance(value, dict):
            raise GatewayError("WhatsApp 网关返回无法识别的数据")
        return value.get("data", value)

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, payload)

    def create(
        self,
        account_id: str,
        phone_e164: str,
        proxy_url: str | None,
        *,
        protocol_definition_id: str,
        protocol_version: str,
        connection_policy: str | object = _UNSET,
        idle_disconnect_seconds: int | object = _UNSET,
        post_verify_grace_seconds: int | object = _UNSET,
        sync_policy: dict[str, bool] | object = _UNSET,
    ) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {"id": account_id, "phoneE164": phone_e164, "state": "unpaired"}
        payload: dict[str, Any] = {
            "id": account_id,
            "protocolDefinitionId": protocol_definition_id,
            "protocolVersion": protocol_version,
            "phoneE164": phone_e164,
            "proxyUrl": proxy_url or "",
        }
        if connection_policy is not _UNSET:
            payload["connectionPolicy"] = connection_policy
        if idle_disconnect_seconds is not _UNSET:
            payload["idleDisconnectSeconds"] = idle_disconnect_seconds
        if post_verify_grace_seconds is not _UNSET:
            payload["postVerifyGraceSeconds"] = post_verify_grace_seconds
        if sync_policy is not _UNSET:
            payload["syncPolicy"] = sync_policy
        value = self._post("/v1/accounts", payload)
        return value if isinstance(value, dict) else {}

    def get(self, account_id: str) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {"id": account_id, "state": "linked_offline"}
        value = self._request("GET", f"/v1/accounts/{account_id}")
        return value if isinstance(value, dict) else {}

    def list(self) -> list[dict[str, Any]]:
        if self.settings.wa_gateway_mock:
            return []
        value = self._request("GET", "/v1/accounts")
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def protocol_info(self) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "protocol": "baileys",
                "name": "Baileys Web",
                "baileysVersion": None,
                "engine": "mock",
                "currentWaWebVersion": None,
                "latestWaWebVersion": None,
                "versionStatus": "unavailable",
                "checkedAt": None,
                "checkError": None,
            }
        value = self._request("GET", "/v1/protocol-info")
        return value if isinstance(value, dict) else {}

    def test_proxy(self, proxy_url: str) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "healthy": True,
                "latencyMs": 0,
                "reasonCategory": "proxy_ok",
            }
        value = self._post("/v1/proxy-check", {"proxyUrl": proxy_url})
        return value if isinstance(value, dict) else {}

    def update_proxy(self, account_id: str, proxy_url: str | None) -> dict[str, Any]:
        return self.update(account_id, proxy_url=proxy_url)

    def update(
        self,
        account_id: str,
        *,
        proxy_url: str | None | object = _UNSET,
        phone_e164: str | object = _UNSET,
        connection_policy: str | object = _UNSET,
        idle_disconnect_seconds: int | object = _UNSET,
        post_verify_grace_seconds: int | object = _UNSET,
        sync_policy: dict[str, bool] | object = _UNSET,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if proxy_url is not _UNSET:
            payload["proxyUrl"] = proxy_url or ""
        if phone_e164 is not _UNSET:
            payload["phoneE164"] = phone_e164
        if connection_policy is not _UNSET:
            payload["connectionPolicy"] = connection_policy
        if idle_disconnect_seconds is not _UNSET:
            payload["idleDisconnectSeconds"] = idle_disconnect_seconds
        if post_verify_grace_seconds is not _UNSET:
            payload["postVerifyGraceSeconds"] = post_verify_grace_seconds
        if sync_policy is not _UNSET:
            payload["syncPolicy"] = sync_policy
        if self.settings.wa_gateway_mock:
            return {"id": account_id, "state": "linked_offline"}
        value = self._request(
            "PATCH", f"/v1/accounts/{account_id}", payload
        )
        return value if isinstance(value, dict) else {}

    def pair(
        self, account_id: str, phone: str | None, method: str, proxy_url: str | None
    ) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "code": "0000-0000",
                "qrPayload": f"mock://pair/{account_id}",
                "expiresAt": (utcnow() + timedelta(minutes=3)).isoformat(),
            }
        return self._post(
            f"/v1/accounts/{account_id}/pairing-code",
            {"phoneE164": phone or ""},
        )

    def reauthenticate(self, account_id: str, phone: str | None) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "code": "0000-0000",
                "expiresAt": (utcnow() + timedelta(minutes=3)).isoformat(),
            }
        value = self._post(
            f"/v1/accounts/{account_id}/reauthentication-code",
            {"phoneE164": phone or ""},
        )
        return value if isinstance(value, dict) else {}

    def sync_metadata(
        self, account_id: str, sync_policy: dict[str, bool]
    ) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "id": account_id,
                "state": "linked_offline",
                "metadataSyncStatus": "ready",
                "quality": {
                    "hasAvatar": None,
                    "groupCount": None,
                    "friendCount": None,
                    "mutualContactCount": None,
                },
            }
        value = self._post(
            f"/v1/accounts/{account_id}/metadata-sync",
            {"syncPolicy": sync_policy},
        )
        return value if isinstance(value, dict) else {}

    def connect(
        self,
        account_id: str,
        proxy_url: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        if proxy_url is not _UNSET:
            self.update_proxy(account_id, proxy_url)
        value = self._post(f"/v1/accounts/{account_id}/connect")
        return value if isinstance(value, dict) else {}

    def disconnect(self, account_id: str) -> dict[str, Any]:
        value = self._post(f"/v1/accounts/{account_id}/disconnect")
        return value if isinstance(value, dict) else {}

    def cancel_pairing(self, account_id: str) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {
                "id": account_id,
                "state": "unpaired",
                "pairingStatus": "cancelled",
            }
        value = self._post(f"/v1/accounts/{account_id}/pairing-cancel")
        return value if isinstance(value, dict) else {}

    def logout(self, account_id: str) -> dict[str, Any]:
        value = self._post(f"/v1/accounts/{account_id}/logout")
        return value if isinstance(value, dict) else {}

    def import_session(
        self,
        account_id: str,
        credentials: dict[str, Any],
        proxy_url: str | None,
        *,
        protocol_definition_id: str,
        protocol_version: str,
    ) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            return {"id": account_id, "state": "validating"}
        value = self._post(
            f"/v1/accounts/{account_id}/import-session",
            {
                "session": credentials,
                "proxyUrl": proxy_url or "",
                "protocolDefinitionId": protocol_definition_id,
                "protocolVersion": protocol_version,
            },
        )
        return value if isinstance(value, dict) else {}

    def export_session(self, account_id: str) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            raise GatewayError("模拟网关没有可导出的账号凭据")
        value = self._request("GET", f"/v1/accounts/{account_id}/export-session")
        if isinstance(value, dict) and isinstance(value.get("session"), dict):
            return value["session"]
        if isinstance(value, dict) and isinstance(value.get("credentials"), dict):
            return value["credentials"]
        return value if isinstance(value, dict) else {}

    def send(
        self,
        account_id: str,
        message_id: str,
        to: str,
        message: str | dict[str, Any],
    ) -> dict[str, Any]:
        if self.settings.wa_gateway_mock:
            digest = hashlib.sha256(f"{account_id}\0{message_id}".encode()).hexdigest()[:16]
            return {
                "messageId": message_id,
                "providerMessageId": f"mock-{digest}",
                "status": "queued",
                "queuedAt": utcnow().isoformat(),
            }
        payload: dict[str, Any] = {"messageId": message_id, "toE164": to}
        if isinstance(message, str):
            payload["text"] = message
        else:
            payload["message"] = message
        return self._post(f"/v1/accounts/{account_id}/messages", payload)
