from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings


class BitlyServiceError(Exception):
    pass


class BitlyClient:
    def __init__(self, access_token: str, *, is_mock: bool = False) -> None:
        self.access_token = access_token
        self.is_mock = is_mock
        self.settings = get_settings()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.settings.bitly_base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(15.0, connect=5.0),
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise BitlyServiceError("无法连接 Bitly，请稍后重试") from exc
        if response.is_success:
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise BitlyServiceError("Bitly 返回了无法识别的数据") from exc
            if isinstance(payload, dict):
                return payload
            raise BitlyServiceError("Bitly 返回了无法识别的数据")
        message = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("description") or "")
        except ValueError:
            pass
        suffix = f"：{message[:300]}" if message else ""
        raise BitlyServiceError(f"Bitly 请求失败（{response.status_code}）{suffix}")

    def discover_group(self) -> str:
        if self.is_mock:
            return "mock_group"
        user = self._request("GET", "/v4/user")
        group_guid = str(user.get("default_group_guid") or "").strip()
        if not group_guid:
            raise BitlyServiceError("Bitly 账号没有默认 Group")
        return group_guid

    def create_bitlink(
        self,
        *,
        target_url: str,
        title: str | None,
        group_guid: str,
        domain: str,
    ) -> dict[str, Any]:
        if self.is_mock:
            slug = secrets.token_urlsafe(6).replace("_", "").replace("-", "")[:8]
            return {
                "id": f"{domain}/{slug}",
                "link": f"https://{domain}/{slug}",
                "long_url": target_url,
                "title": title,
                "archived": False,
            }
        payload: dict[str, Any] = {
            "long_url": target_url,
            "domain": domain,
            "group_guid": group_guid,
            "force_new_link": True,
        }
        if title:
            payload["title"] = title
        return self._request("POST", "/v4/bitlinks", json=payload)

    def update_bitlink(
        self,
        bitlink_id: str,
        *,
        target_url: str | None = None,
        title: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        if self.is_mock:
            return {
                "id": bitlink_id,
                "link": f"https://{bitlink_id}",
                "long_url": target_url,
                "title": title,
                "archived": archived,
            }
        payload: dict[str, Any] = {}
        if target_url is not None:
            payload["long_url"] = target_url
        if title is not None:
            payload["title"] = title
        if archived is not None:
            payload["archived"] = archived
        return self._request(
            "PATCH",
            f"/v4/bitlinks/{quote(bitlink_id, safe='/')}",
            json=payload,
        )
