from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=512)
    turnstile_token: str | None = Field(
        default=None, alias="turnstileToken", max_length=4096
    )


class UserCreate(ApiModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=512)
    display_name: str | None = Field(default=None, alias="displayName", max_length=120)
    group_id: str = Field(
        alias="groupId", validation_alias=AliasChoices("roleId", "groupId", "group_id")
    )
    is_active: bool = Field(
        default=True,
        validation_alias=AliasChoices("isActive", "enabled", "is_active"),
    )


class UserUpdate(ApiModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=8, max_length=512)
    display_name: str | None = Field(default=None, alias="displayName", max_length=120)
    group_id: str | None = Field(
        default=None,
        alias="groupId",
        validation_alias=AliasChoices("roleId", "groupId", "group_id"),
    )
    is_active: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isActive", "enabled", "is_active"),
    )


class GroupCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class GroupUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class RoleCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    menu_ids: list[str] = Field(default_factory=list, alias="menuIds", max_length=500)
    permission_keys: list[str] = Field(
        default_factory=list, alias="permissionKeys", max_length=500
    )
    enabled: bool = True


class RoleUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    menu_ids: list[str] | None = Field(default=None, alias="menuIds", max_length=500)
    permission_keys: list[str] | None = Field(
        default=None, alias="permissionKeys", max_length=500
    )
    enabled: bool | None = None


class MenuCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    menu_type: Literal["directory", "page"] = Field(alias="type")
    parent_id: str | None = Field(default=None, alias="parentId", max_length=64)
    route_path: str | None = Field(default=None, alias="routePath", max_length=255)
    icon: str | None = Field(default=None, max_length=80)
    permission_key: str | None = Field(
        default=None, alias="permissionKey", max_length=120
    )
    sort_order: int = Field(default=0, alias="sortOrder", ge=0, le=100000)
    enabled: bool = True
    visible: bool = True


class MenuUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, alias="parentId", max_length=64)
    route_path: str | None = Field(default=None, alias="routePath", max_length=255)
    icon: str | None = Field(default=None, max_length=80)
    permission_key: str | None = Field(
        default=None, alias="permissionKey", max_length=120
    )
    sort_order: int | None = Field(default=None, alias="sortOrder", ge=0, le=100000)
    enabled: bool | None = None
    visible: bool | None = None


class BitlyAccountCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    access_token: str | None = Field(default=None, alias="accessToken", max_length=2048)
    group_guid: str | None = Field(default=None, alias="groupGuid", max_length=80)
    short_domain: str = Field(default="bit.ly", alias="shortDomain", max_length=255)
    enabled: bool = True


class BitlyAccountUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    access_token: str | None = Field(default=None, alias="accessToken", max_length=2048)
    group_guid: str | None = Field(default=None, alias="groupGuid", max_length=80)
    short_domain: str | None = Field(default=None, alias="shortDomain", max_length=255)
    enabled: bool | None = None


class DirectShortLinkCreate(ApiModel):
    target_url: AnyHttpUrl = Field(alias="targetUrl")
    title: str | None = Field(default=None, max_length=255)
    provider_account_id: str | None = Field(default=None, alias="providerAccountId")

    @field_validator("target_url")
    @classmethod
    def only_http(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme not in {"http", "https"}:
            raise ValueError("only http and https target URLs are supported")
        return value


class DirectShortLinkUpdate(ApiModel):
    target_url: AnyHttpUrl | None = Field(default=None, alias="targetUrl")
    title: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None

    @field_validator("target_url")
    @classmethod
    def only_http(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and value.scheme not in {"http", "https"}:
            raise ValueError("only http and https target URLs are supported")
        return value


class MetaPixelCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=120)
    capi_token: str | None = Field(default=None, alias="capiToken", max_length=4096)
    enabled: bool = True

    @field_validator("dataset_id")
    @classmethod
    def safe_dataset_id(cls, value: str) -> str:
        if not all(char.isalnum() or char in "_.:-" for char in value):
            raise ValueError("Pixel / Dataset ID 包含不安全字符")
        return value


class MetaPixelUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    dataset_id: str | None = Field(default=None, alias="datasetId", min_length=1, max_length=120)
    capi_token: str | None = Field(default=None, alias="capiToken", max_length=4096)
    enabled: bool | None = None

    @field_validator("dataset_id")
    @classmethod
    def safe_dataset_id(cls, value: str | None) -> str | None:
        if value is not None and not all(
            char.isalnum() or char in "_.:-" for char in value
        ):
            raise ValueError("Pixel / Dataset ID 包含不安全字符")
        return value


class ProxyEndpointCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["http", "https", "socks5"]
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=4096)
    country_code: str | None = Field(default=None, alias="countryCode", max_length=2)
    provider: str | None = Field(default=None, max_length=120)
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        host = value.strip().strip("[]").lower().rstrip(".")
        if not host or any(char in host for char in "/?#@") or any(char.isspace() for char in host):
            raise ValueError("代理主机格式不正确")
        return host

    @field_validator("country_code")
    @classmethod
    def valid_country_code(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        normalized = value.upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("国家代码必须是两个字母")
        return normalized


class ProxyEndpointBulkCreate(ApiModel):
    lines: list[str] = Field(min_length=1, max_length=1000)
    default_protocol: Literal["http", "https", "socks5"] = Field(
        default="http", alias="defaultProtocol"
    )
    country_code: str | None = Field(default=None, alias="countryCode", max_length=2)
    provider: str | None = Field(default=None, max_length=120)
    enabled: bool = True

    @field_validator("lines")
    @classmethod
    def valid_lines(cls, value: list[str]) -> list[str]:
        if any(len(line) > 8192 for line in value):
            raise ValueError("单行代理配置不能超过 8192 个字符")
        return value

    @field_validator("country_code")
    @classmethod
    def valid_country_code(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        normalized = value.upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("国家代码必须是两个字母")
        return normalized


class ProxyEndpointUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: Literal["http", "https", "socks5"] | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=4096)
    country_code: str | None = Field(default=None, alias="countryCode", max_length=2)
    provider: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = value.strip().strip("[]").lower().rstrip(".")
        if not host or any(char in host for char in "/?#@") or any(char.isspace() for char in host):
            raise ValueError("代理主机格式不正确")
        return host

    @field_validator("country_code")
    @classmethod
    def valid_country_code(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        normalized = value.upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("国家代码必须是两个字母")
        return normalized


class IpAllocationPolicyUpdate(ApiModel):
    allocation_mode: Literal[
        "strict_one_to_one", "tenant_reuse", "least_load", "manual"
    ] = Field(default="least_load", alias="allocationMode")
    country_match: Literal["strict", "prefer", "off"] = Field(
        default="prefer", alias="countryMatch"
    )
    max_accounts_per_ip: int = Field(
        default=100, alias="maxAccountsPerIp", ge=1, le=10000
    )
    avoid_unhealthy: bool = Field(default=True, alias="avoidUnhealthy")
    sticky_binding: bool = Field(default=True, alias="stickyBinding")


class AccountProxyBindingCreate(ApiModel):
    account_id: str = Field(
        alias="accountId",
        validation_alias=AliasChoices("accountId", "accountPublicId"),
        min_length=1,
        max_length=120,
    )
    proxy_id: str = Field(
        alias="proxyId",
        validation_alias=AliasChoices("proxyId", "proxyPublicId"),
        min_length=1,
        max_length=64,
    )


class AccountProxyBindingUpdate(ApiModel):
    proxy_id: str = Field(
        alias="proxyId",
        validation_alias=AliasChoices("proxyId", "proxyPublicId"),
        min_length=1,
        max_length=64,
    )
