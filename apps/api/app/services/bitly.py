from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings


class BitlyServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        category: str = "configuration",
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after


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
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            raise BitlyServiceError(
                "Bitly 请求超时，请稍后重试",
                category="temporary",
            ) from exc
        except httpx.HTTPError as exc:
            raise BitlyServiceError(
                "无法连接 Bitly，请稍后重试",
                category="temporary",
            ) from exc
        if response.is_success:
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise BitlyServiceError(
                    "Bitly 返回了无法识别的数据",
                    category="temporary",
                ) from exc
            if isinstance(payload, dict):
                return payload
            raise BitlyServiceError(
                "Bitly 返回了无法识别的数据",
                category="temporary",
            )

        payload: dict[str, Any] = {}
        try:
            decoded = response.json()
            if isinstance(decoded, dict):
                payload = decoded
        except ValueError:
            pass
        code = str(payload.get("message") or payload.get("code") or "").strip()
        description = str(payload.get("description") or payload.get("resource") or "").strip()
        detail = " ".join(value for value in (code, description) if value)[:300]
        upper_detail = detail.upper()
        retry_after: int | None = None
        try:
            retry_after = int(response.headers.get("Retry-After", ""))
        except ValueError:
            pass
        if response.status_code in {401, 403} and "LIMIT" not in upper_detail:
            category = "invalid"
        elif any(
            marker in upper_detail
            for marker in (
                "USAGE_LIMIT",
                "MONTHLY_LIMIT",
                "PLAN_LIMIT",
                "ENCODE_LIMIT",
            )
        ):
            category = "quota_exhausted"
        elif response.status_code == 429:
            category = "rate_limited"
        elif response.status_code >= 500:
            category = "temporary"
        else:
            category = "configuration"
        suffix = f"：{detail}" if detail else ""
        raise BitlyServiceError(
            f"Bitly 请求失败（{response.status_code}）{suffix}",
            category=category,
            status_code=response.status_code,
            retry_after=retry_after,
        )

    def user(self) -> dict[str, Any]:
        if self.is_mock:
            return {
                "login": "local-bitly-mock",
                "name": "Bitly 本地模拟账号",
                "default_group_guid": "mock_group",
            }
        return self._request("GET", "/v4/user")

    def groups(self) -> list[dict[str, Any]]:
        if self.is_mock:
            return [
                {
                    "name": "本地模拟 Group",
                    "guid": "mock_group",
                    "bsds": ["bit.ly"],
                }
            ]
        payload = self._request("GET", "/v4/groups")
        rows = payload.get("groups")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def group_preferences(self, group_guid: str) -> dict[str, Any]:
        if self.is_mock:
            return {"group_guid": group_guid, "domain_preference": "bit.ly"}
        return self._request(
            "GET",
            f"/v4/groups/{quote(group_guid, safe='')}/preferences",
        )

    def discover_account(self) -> dict[str, str]:
        user = self.user()
        groups = self.groups()
        default_group_guid = str(user.get("default_group_guid") or "").strip()
        group = next(
            (
                row
                for row in groups
                if str(row.get("guid") or "").strip() == default_group_guid
            ),
            groups[0] if groups else None,
        )
        if group is None:
            raise BitlyServiceError("Bitly 账号没有可用的 Group")
        group_guid = str(group.get("guid") or "").strip()
        if not group_guid:
            raise BitlyServiceError("Bitly Group 缺少 GUID")

        domain = ""
        try:
            preferences = self.group_preferences(group_guid)
            domain = str(preferences.get("domain_preference") or "").strip()
        except BitlyServiceError:
            # Group details also contain assigned branded domains. A preferences
            # outage must not prevent a valid token from being saved.
            pass
        if not domain:
            bsds = group.get("bsds")
            if isinstance(bsds, list):
                domain = next(
                    (
                        str(item).strip()
                        for item in bsds
                        if isinstance(item, str) and item.strip()
                    ),
                    "",
                )
        display_name = str(
            user.get("name")
            or user.get("login")
            or group.get("name")
            or "Bitly 账号"
        ).strip()
        return {
            "name": display_name[:120] or "Bitly 账号",
            "groupGuid": group_guid,
            "shortDomain": domain or "bit.ly",
        }

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

    def click_summary(self, bitlink_id: str) -> dict[str, Any]:
        if self.is_mock:
            return {"total_clicks": 0, "unit": "day", "units": -1}
        return self._request(
            "GET",
            f"/v4/bitlinks/{quote(bitlink_id, safe='/')}/clicks/summary",
            params={"unit": "day", "units": -1},
        )
