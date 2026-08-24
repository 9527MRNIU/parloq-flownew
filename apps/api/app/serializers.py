from __future__ import annotations

from typing import Any

from app.entity_ids import entity_id
from app.models import (
    AccountProxyBinding,
    BitlyProviderAccount,
    DirectShortLink,
    MetaPixel,
    ProxyEndpoint,
    UserAccount,
    UserGroup,
)


def iso(value: object | None) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def user_row(user: UserAccount, group: UserGroup | None = None) -> dict[str, Any]:
    resolved_group = group or user.group
    return {
        "id": str(user.id),
        "username": user.username,
        "displayName": user.display_name,
        "groupId": str(user.group_id),
        "roleId": str(user.group_id),
        "groupName": resolved_group.name if resolved_group else None,
        "role": user.role,
        "isAdmin": user.role == "admin",
        "isActive": user.is_active,
        "enabled": user.is_active,
        "mfaEnabled": bool(
            user.mfa_credential and user.mfa_credential.enabled_at is not None
        ),
        "lastLoginAt": iso(user.last_login_at),
        "createdAt": iso(user.created_at),
        "updatedAt": iso(user.updated_at),
    }


def group_row(group: UserGroup, user_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "name": group.name,
        "systemKey": group.system_key,
        "description": group.description,
        "isBuiltin": group.is_builtin,
        "enabled": group.enabled,
        "userCount": user_count,
        "createdAt": iso(group.created_at),
        "updatedAt": iso(group.updated_at),
    }


def bitly_account_row(account: BitlyProviderAccount) -> dict[str, Any]:
    return {
        "id": entity_id(account),
        "provider": "bitly",
        "name": account.name,
        "tokenMasked": f"••••{account.token_last4}" if account.token_last4 else "已保存",
        "groupGuid": account.group_guid,
        "shortDomain": account.short_domain,
        "enabled": account.enabled,
        "status": account.status,
        "isMock": account.is_mock,
        "lastError": account.last_error,
        "cooldownUntil": iso(account.cooldown_until),
        "lastUsedAt": iso(account.last_used_at),
        "createdAt": iso(account.created_at),
        "updatedAt": iso(account.updated_at),
    }


def direct_short_link_row(link: DirectShortLink) -> dict[str, Any]:
    return {
        "id": entity_id(link),
        "title": link.title,
        "targetUrl": link.target_url,
        "bitlinkId": link.bitlink_id,
        "shortUrl": link.short_url,
        "providerAccountId": entity_id(link.provider_account),
        "providerAccountName": link.provider_account.name,
        "enabled": link.enabled,
        "status": link.status,
        "lastError": link.last_error,
        "clickCount": link.click_count,
        "clicksSyncedAt": iso(link.clicks_synced_at),
        "createdAt": iso(link.created_at),
        "updatedAt": iso(link.updated_at),
    }


def meta_pixel_row(pixel: MetaPixel) -> dict[str, Any]:
    from app.services.meta_conversions import normalized_meta_event_mapping

    return {
        "id": entity_id(pixel),
        "name": pixel.name,
        "datasetId": pixel.dataset_id,
        "capiTokenMasked": f"••••{pixel.capi_token_last4}" if pixel.capi_token_last4 else None,
        "capiTokenConfigured": bool(pixel.capi_token_ciphertext),
        "browserPixelEnabled": pixel.browser_pixel_enabled,
        "capiEnabled": pixel.capi_enabled,
        "eventMapping": normalized_meta_event_mapping(pixel.event_mapping_json),
        "enabled": pixel.enabled,
        "createdAt": iso(pixel.created_at),
        "updatedAt": iso(pixel.updated_at),
    }


def proxy_endpoint_row(proxy: ProxyEndpoint, assigned_count: int = 0) -> dict[str, Any]:
    return {
        "id": entity_id(proxy),
        "name": proxy.name,
        "protocol": proxy.protocol,
        "host": proxy.host,
        "port": proxy.port,
        "usernameMasked": f"••••{proxy.username_last4}" if proxy.username_last4 else None,
        "passwordMasked": f"••••{proxy.password_last4}" if proxy.password_last4 else None,
        "countryCode": proxy.country_code,
        "provider": proxy.provider,
        "enabled": proxy.enabled,
        "healthStatus": proxy.health_status,
        "lastCheckedAt": iso(proxy.last_checked_at),
        "lastError": proxy.last_error,
        "consecutiveFailures": proxy.consecutive_failures,
        "cooldownUntil": iso(proxy.cooldown_until),
        "lastSuccessAt": iso(proxy.last_success_at),
        "lastFailureAt": iso(proxy.last_failure_at),
        "lastCheckSource": proxy.last_check_source,
        "latencyMs": proxy.latency_ms,
        "assignedAccountCount": assigned_count,
        "createdAt": iso(proxy.created_at),
        "updatedAt": iso(proxy.updated_at),
    }


def account_proxy_binding_row(
    binding: AccountProxyBinding,
    account_id: str | None = None,
    account_name: str | None = None,
    account_phone: str | None = None,
) -> dict[str, Any]:
    row = {
        "id": str(binding.id),
        "proxyId": entity_id(binding.proxy),
        "proxyName": binding.proxy.name,
        "countryCode": binding.proxy.country_code,
        "createdAt": iso(binding.created_at),
        "updatedAt": iso(binding.updated_at),
    }
    if account_id is not None:
        row["accountId"] = account_id
        row["accountName"] = account_name
        row["accountPhone"] = account_phone
    return row
