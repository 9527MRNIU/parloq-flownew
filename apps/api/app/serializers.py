from __future__ import annotations

from typing import Any

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
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "groupId": user.group_id,
        "roleId": user.group_id,
        "groupName": resolved_group.name if resolved_group else None,
        "role": user.role,
        "isAdmin": user.role == "admin",
        "isActive": user.is_active,
        "enabled": user.is_active,
        "lastLoginAt": iso(user.last_login_at),
        "createdAt": iso(user.created_at),
        "updatedAt": iso(user.updated_at),
    }


def group_row(group: UserGroup, user_count: int = 0) -> dict[str, Any]:
    return {
        "id": group.id,
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
        "id": account.public_id,
        "publicId": account.public_id,
        "provider": "bitly",
        "name": account.name,
        "tokenMasked": f"••••{account.token_last4}" if account.token_last4 else "已保存",
        "groupGuid": account.group_guid,
        "shortDomain": account.short_domain,
        "enabled": account.enabled,
        "status": account.status,
        "isMock": account.is_mock,
        "createdAt": iso(account.created_at),
        "updatedAt": iso(account.updated_at),
    }


def direct_short_link_row(link: DirectShortLink) -> dict[str, Any]:
    return {
        "id": link.public_id,
        "publicId": link.public_id,
        "title": link.title,
        "targetUrl": link.target_url,
        "bitlinkId": link.bitlink_id,
        "shortUrl": link.short_url,
        "providerAccountId": link.provider_account.public_id,
        "providerAccountName": link.provider_account.name,
        "enabled": link.enabled,
        "status": link.status,
        "lastError": link.last_error,
        "createdAt": iso(link.created_at),
        "updatedAt": iso(link.updated_at),
    }


def meta_pixel_row(pixel: MetaPixel) -> dict[str, Any]:
    return {
        "id": pixel.public_id,
        "publicId": pixel.public_id,
        "name": pixel.name,
        "datasetId": pixel.dataset_id,
        "capiTokenMasked": f"••••{pixel.capi_token_last4}" if pixel.capi_token_last4 else None,
        "enabled": pixel.enabled,
        "createdAt": iso(pixel.created_at),
        "updatedAt": iso(pixel.updated_at),
    }


def proxy_endpoint_row(proxy: ProxyEndpoint, assigned_count: int = 0) -> dict[str, Any]:
    return {
        "id": proxy.public_id,
        "publicId": proxy.public_id,
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
        "assignedAccountCount": assigned_count,
        "createdAt": iso(proxy.created_at),
        "updatedAt": iso(proxy.updated_at),
    }


def account_proxy_binding_row(binding: AccountProxyBinding) -> dict[str, Any]:
    return {
        "id": binding.public_id,
        "publicId": binding.public_id,
        "accountPublicId": binding.account_public_id,
        "proxyPublicId": binding.proxy.public_id,
        "proxyName": binding.proxy.name,
        "countryCode": binding.proxy.country_code,
        "createdAt": iso(binding.created_at),
        "updatedAt": iso(binding.updated_at),
    }
