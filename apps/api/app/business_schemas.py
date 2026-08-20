from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validation import normalize_country, normalize_phone, normalize_slug, validate_structured_json
from app.snowflake import parse_snowflake_id
from app.hyperlink_messages import validate_hyperlink_template_content
from app.message_capabilities import TextMaterialRole, validate_text_material_content


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class PersonalAccountCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")
    enabled: bool = True
    marketing_eligible: bool = Field(default=True, alias="marketingEligible")
    proxy_id: str | None = Field(
        default=None,
        alias="proxyId",
        validation_alias=AliasChoices("proxyId", "proxyPublicId"),
        max_length=64,
    )
    group_id: str | None = Field(default=None, alias="groupId", max_length=20)
    source_ref_type: str | None = Field(default=None, alias="sourceRefType", max_length=40)
    source_ref_id: str | None = Field(default=None, alias="sourceRefId", max_length=64)
    protocol_id: str | None = Field(
        default=None, alias="protocolId", max_length=64
    )

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)
    _country = field_validator("country_code")(normalize_country)
    _group_id = field_validator("group_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )
    _source_ref_id = field_validator("source_ref_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )


class PersonalAccountUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")
    enabled: bool | None = None
    marketing_eligible: bool | None = Field(
        default=None, alias="marketingEligible"
    )
    proxy_id: str | None = Field(
        default=None,
        alias="proxyId",
        validation_alias=AliasChoices("proxyId", "proxyPublicId"),
        max_length=64,
    )
    group_id: str | None = Field(default=None, alias="groupId", max_length=20)

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)
    _country = field_validator("country_code")(normalize_country)
    _group_id = field_validator("group_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )


class AccountBatchExport(Model):
    account_ids: list[str] = Field(alias="accountIds", min_length=1, max_length=100)
    export_format: Literal["baileys_creds", "native"] = Field(
        default="baileys_creds", alias="format"
    )

    @field_validator("account_ids")
    @classmethod
    def snowflake_account_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(parse_snowflake_id(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("账号 ID 不能重复")
        return normalized


class AccountGroupCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class AccountGroupUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ProtocolSyncPolicy(Model):
    avatar: bool = True
    profile_status: bool = Field(default=True, alias="profileStatus")
    business_profile: bool = Field(default=True, alias="businessProfile")
    group_summary: bool = Field(default=True, alias="groupSummary")
    group_details: bool = Field(default=False, alias="groupDetails")
    contacts: bool = False
    chats: bool = False
    message_history: bool = Field(default=False, alias="messageHistory")
    privacy_settings: bool = Field(default=False, alias="privacySettings")
    blocklist: bool = False

    @model_validator(mode="after")
    def group_details_include_summary(self):
        if self.group_details:
            self.group_summary = True
        return self


class ProtocolRateLimitRule(Model):
    max_requests: int = Field(alias="maxRequests", ge=1, le=100_000)
    window_seconds: int = Field(alias="windowSeconds", ge=1, le=86_400)


class OptionalProtocolRateLimitRule(Model):
    max_requests: int | None = Field(
        default=None,
        alias="maxRequests",
        ge=1,
        le=100_000,
    )
    window_seconds: int = Field(alias="windowSeconds", ge=1, le=86_400)


class ProtocolRateLimitPolicy(Model):
    visitor_check: ProtocolRateLimitRule = Field(
        default=ProtocolRateLimitRule(maxRequests=5, windowSeconds=600),
        alias="visitorCheck",
    )
    visitor_attempt: ProtocolRateLimitRule = Field(
        default=ProtocolRateLimitRule(maxRequests=5, windowSeconds=600),
        alias="visitorAttempt",
    )
    ip_start: ProtocolRateLimitRule = Field(
        default=ProtocolRateLimitRule(maxRequests=5, windowSeconds=600),
        alias="ipStart",
    )
    phone_attempt: ProtocolRateLimitRule = Field(
        default=ProtocolRateLimitRule(maxRequests=5, windowSeconds=600),
        alias="phoneAttempt",
    )
    channel_attempt: OptionalProtocolRateLimitRule = Field(
        default=OptionalProtocolRateLimitRule(
            maxRequests=None,
            windowSeconds=60,
        ),
        alias="channelAttempt",
    )
    status: ProtocolRateLimitRule = ProtocolRateLimitRule(
        maxRequests=60, windowSeconds=60
    )
    cancel: ProtocolRateLimitRule = ProtocolRateLimitRule(
        maxRequests=5, windowSeconds=600
    )


class ProtocolNodeCreate(Model):
    name: str = Field(min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    ingress_enabled: bool = Field(default=True, alias="ingressEnabled")
    marketing_enabled: bool = Field(default=True, alias="marketingEnabled")
    max_account_count: int | None = Field(
        default=None, alias="maxAccountCount", ge=0
    )
    max_online_accounts: int | None = Field(
        default=1000, alias="maxOnlineAccounts", ge=0
    )
    max_concurrent_pairings: int | None = Field(
        default=None, alias="maxConcurrentPairings", ge=0
    )
    connection_policy: Literal["on_demand", "always_on"] = Field(
        default="on_demand", alias="connectionPolicy"
    )
    idle_disconnect_seconds: int = Field(
        default=600, alias="idleDisconnectSeconds", ge=60, le=86400
    )
    post_verify_grace_seconds: int = Field(
        default=120, alias="postVerifyGraceSeconds", ge=0, le=3600
    )
    sync_policy: ProtocolSyncPolicy = Field(
        default_factory=ProtocolSyncPolicy, alias="syncPolicy"
    )
    rate_limit_policy: ProtocolRateLimitPolicy = Field(
        default_factory=ProtocolRateLimitPolicy, alias="rateLimitPolicy"
    )


class ProtocolNodeUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    ingress_enabled: bool | None = Field(default=None, alias="ingressEnabled")
    marketing_enabled: bool | None = Field(default=None, alias="marketingEnabled")
    max_account_count: int | None = Field(
        default=None, alias="maxAccountCount", ge=0
    )
    max_online_accounts: int | None = Field(
        default=None, alias="maxOnlineAccounts", ge=0
    )
    max_concurrent_pairings: int | None = Field(
        default=None, alias="maxConcurrentPairings", ge=0
    )
    connection_policy: Literal["on_demand", "always_on"] | None = Field(
        default=None, alias="connectionPolicy"
    )
    idle_disconnect_seconds: int | None = Field(
        default=None, alias="idleDisconnectSeconds", ge=60, le=86400
    )
    post_verify_grace_seconds: int | None = Field(
        default=None, alias="postVerifyGraceSeconds", ge=0, le=3600
    )
    sync_policy: ProtocolSyncPolicy | None = Field(
        default=None, alias="syncPolicy"
    )
    rate_limit_policy: ProtocolRateLimitPolicy | None = Field(
        default=None, alias="rateLimitPolicy"
    )


class ProtocolPoolMemberInput(Model):
    protocol_node_id: str = Field(alias="protocolNodeId", max_length=20)
    priority: int = Field(default=100, ge=0, le=1_000_000)
    enabled: bool = True

    _protocol_node_id = field_validator("protocol_node_id")(
        lambda value: str(parse_snowflake_id(value))
    )


class ProtocolPoolCreate(Model):
    name: str = Field(min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    members: list[ProtocolPoolMemberInput] = Field(default_factory=list, max_length=100)

    @field_validator("members")
    @classmethod
    def unique_members(
        cls, values: list[ProtocolPoolMemberInput]
    ) -> list[ProtocolPoolMemberInput]:
        ids = [value.protocol_node_id for value in values]
        if len(set(ids)) != len(ids):
            raise ValueError("协议池成员不能重复")
        return values


class ProtocolPoolUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    members: list[ProtocolPoolMemberInput] | None = Field(
        default=None, max_length=100
    )

    @field_validator("members")
    @classmethod
    def unique_members(
        cls, values: list[ProtocolPoolMemberInput] | None
    ) -> list[ProtocolPoolMemberInput] | None:
        if values is None:
            return values
        ids = [value.protocol_node_id for value in values]
        if len(set(ids)) != len(ids):
            raise ValueError("协议池成员不能重复")
        return values


class ProtocolBatchAction(Model):
    protocol_ids: list[str] = Field(
        alias="protocolIds", min_length=1, max_length=1000
    )


class PromotionEventRateLimitRule(Model):
    max_requests: int = Field(alias="maxRequests", ge=1, le=1_000_000)
    window_seconds: int = Field(alias="windowSeconds", ge=1, le=86_400)


class PromotionEventRateLimitPolicy(Model):
    session_reports: PromotionEventRateLimitRule = Field(
        default=PromotionEventRateLimitRule(
            maxRequests=60, windowSeconds=60
        ),
        alias="sessionReports",
    )
    ip_reports: PromotionEventRateLimitRule = Field(
        default=PromotionEventRateLimitRule(
            maxRequests=600, windowSeconds=60
        ),
        alias="ipReports",
    )
    channel_reports: PromotionEventRateLimitRule = Field(
        default=PromotionEventRateLimitRule(
            maxRequests=10_000, windowSeconds=60
        ),
        alias="channelReports",
    )
    meta_domain_reports: PromotionEventRateLimitRule = Field(
        default=PromotionEventRateLimitRule(
            maxRequests=5, windowSeconds=600
        ),
        alias="metaDomainReports",
    )


class PromotionTemplatePolicyUpdate(Model):
    protection_mode: Literal["basic", "enhanced", "strict"] | None = Field(
        default=None, alias="protectionMode"
    )
    devtools_action: Literal["log", "block", "blank"] | None = Field(
        default=None, alias="devtoolsAction"
    )
    lock_viewport_zoom: bool | None = Field(
        default=None, alias="lockViewportZoom"
    )
    device_signals: Literal[
        "off", "standard", "enhanced", "fingerprint"
    ] | None = Field(
        default=None, alias="deviceSignals"
    )
    event_rate_limit_policy: PromotionEventRateLimitPolicy | None = Field(
        default=None, alias="eventRateLimitPolicy"
    )


def _validate_integration_key(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]{0,78}[a-z0-9])?", normalized):
        raise ValueError("集成标识只能包含小写字母、数字、点、下划线和连字符")
    return normalized


class PromotionIntegrationCreate(Model):
    integration_key: str = Field(alias="integrationKey", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    domain_id: str = Field(alias="domainId", min_length=1, max_length=20)
    enabled: bool = True

    _key = field_validator("integration_key")(_validate_integration_key)
    _domain_id = field_validator("domain_id")(
        lambda value: str(parse_snowflake_id(value))
    )


class PromotionIntegrationUpdate(Model):
    integration_key: str | None = Field(
        default=None, alias="integrationKey", min_length=1, max_length=80
    )
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    domain_id: str | None = Field(default=None, alias="domainId", max_length=20)
    enabled: bool | None = None

    _key = field_validator("integration_key")(
        lambda value: _validate_integration_key(value) if value is not None else None
    )
    _domain_id = field_validator("domain_id")(
        lambda value: str(parse_snowflake_id(value)) if value is not None else None
    )


class PromotionRepositoryIntegrationImport(Model):
    domain_id: str | None = Field(default=None, alias="domainId", max_length=20)
    enabled: bool = True

    _domain_id = field_validator("domain_id")(
        lambda value: str(parse_snowflake_id(value)) if value is not None else None
    )


class PromotionTemplateIntegrationsUpdate(Model):
    integration_ids: list[str] = Field(
        default_factory=list, alias="integrationIds", max_length=50
    )

    @field_validator("integration_ids")
    @classmethod
    def valid_integration_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(parse_snowflake_id(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("模板集成不能重复")
        return normalized


class PairRequest(Model):
    phone: str | None = None
    method: Literal["pairing_code", "qr_code"] = "pairing_code"

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)


class SendRequest(Model):
    to: str
    message: str = Field(min_length=1, max_length=4096)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=160)

    _to = field_validator("to")(normalize_phone)


class DomainCreate(Model):
    hostname: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    management_mode: Literal["external", "platform"] = Field(
        default="external", alias="managementMode"
    )

    @field_validator("hostname")
    @classmethod
    def domain(cls, value: str) -> str:
        hostname = value.lower().strip().rstrip(".")
        if "/" in hostname or ":" in hostname or " " in hostname or "." not in hostname:
            raise ValueError("域名格式不正确")
        return hostname


class ProviderDomainImport(Model):
    provider: Literal["cloudflare", "namesilo"]
    hostname: str = Field(min_length=1, max_length=255)
    confirm_dns_replace: bool = Field(alias="confirmDnsReplace")

    @field_validator("hostname")
    @classmethod
    def domain(cls, value: str) -> str:
        hostname = value.lower().strip().rstrip(".")
        if "/" in hostname or ":" in hostname or " " in hostname or "." not in hostname:
            raise ValueError("域名格式不正确")
        return hostname


class DomainUpdate(Model):
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    management_mode: Literal["external", "platform"] | None = Field(
        default=None, alias="managementMode"
    )
    auto_renew: bool | None = Field(default=None, alias="autoRenew")

    @field_validator("hostname")
    @classmethod
    def domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        hostname = value.lower().strip().rstrip(".")
        if "/" in hostname or ":" in hostname or " " in hostname or "." not in hostname:
            raise ValueError("域名格式不正确")
        return hostname


class DomainQuoteRequest(Model):
    hostname: str = Field(min_length=1, max_length=255)
    years: int = Field(default=1, ge=1, le=10)

    @field_validator("hostname")
    @classmethod
    def domain(cls, value: str) -> str:
        hostname = value.lower().strip().rstrip(".")
        if "/" in hostname or ":" in hostname or " " in hostname or "." not in hostname:
            raise ValueError("域名格式不正确")
        return hostname


class DomainSearchRequest(Model):
    label: str = Field(min_length=1, max_length=189)
    years: int = Field(default=1, ge=1, le=10)

    @field_validator("label")
    @classmethod
    def domain_label(cls, value: str) -> str:
        label = value.lower().strip().rstrip(".")
        parts = label.split(".")
        if any(
            not part
            or len(part) > 63
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) is None
            for part in parts
        ):
            raise ValueError("域名主体格式不正确")
        return label


class DomainOrderCreate(Model):
    quote_id: str = Field(alias="quoteId", min_length=1, max_length=64)
    auto_renew: bool = Field(default=False, alias="autoRenew")


class StructuredCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    content_json: dict = Field(alias="contentJson")
    enabled: bool = True

    _content = field_validator("content_json")(validate_structured_json)


class PromotionTemplateUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "disabled"] | None = None


class PromotionChannelCreate(Model):
    channel_type: Literal["facebook"] = Field(default="facebook", alias="type")
    name: str = Field(min_length=1, max_length=120)
    country_code: str = Field(alias="countryCode")
    template_id: str = Field(
        alias="templateId",
        validation_alias=AliasChoices("templateId", "templatePublicId"),
    )
    domain_id: str | None = Field(
        default=None,
        alias="domainId",
        validation_alias=AliasChoices("domainId", "domainPublicId"),
    )
    subdomain_prefix: str | None = Field(
        default=None, alias="subdomainPrefix", max_length=63
    )
    slug: str
    pixel_id: str | None = Field(
        default=None,
        alias="pixelId",
        validation_alias=AliasChoices("pixelId", "pixelPublicId"),
    )
    account_group_id: str | None = Field(
        default=None,
        alias="accountGroupId",
        validation_alias=AliasChoices("accountGroupId", "accountGroupPublicId"),
    )
    protocol_node_id: str | None = Field(
        default=None, alias="protocolNodeId", max_length=20
    )
    protocol_pool_id: str | None = Field(
        default=None, alias="protocolPoolId", max_length=20
    )
    meta_browser_pixel_enabled: bool = Field(
        default=True, alias="metaBrowserPixelEnabled"
    )
    meta_capi_enabled: bool = Field(default=False, alias="metaCapiEnabled")
    meta_event_mapping: dict[str, str | None] = Field(
        default_factory=lambda: {
            "page_view": "PageView",
            "phone_submit": "Lead",
            "pairing_started": "InitiateCheckout",
            "pairing_verified": "CompleteRegistration",
        },
        alias="metaEventMapping",
    )
    in_app_browser_mode: Literal["allow", "guide_external"] = Field(
        default="guide_external", alias="inAppBrowserMode"
    )
    new_account_marketing_enabled: bool = Field(
        default=True, alias="newAccountMarketingEnabled"
    )
    locale_mode: Literal["auto", "fixed"] = Field(default="auto", alias="localeMode")
    locale: str | None = Field(default=None, max_length=16)
    status: Literal["draft", "active", "paused"] = "draft"
    launch_at: datetime | None = Field(default=None, alias="launchAt")

    _country = field_validator("country_code")(normalize_country)
    _slug = field_validator("slug")(normalize_slug)
    _protocol_node_id = field_validator("protocol_node_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )
    _protocol_pool_id = field_validator("protocol_pool_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )

    @model_validator(mode="after")
    def one_protocol_route(self):
        if self.protocol_node_id and self.protocol_pool_id:
            raise ValueError("渠道只能绑定协议节点或协议池中的一种")
        return self

    @field_validator("meta_event_mapping")
    @classmethod
    def valid_meta_event_mapping(
        cls, value: dict[str, str | None]
    ) -> dict[str, str]:
        from app.services.meta_conversions import (
            META_EVENT_KEYS,
            META_STANDARD_EVENTS,
            normalized_meta_event_mapping,
        )

        unknown = set(value).difference(META_EVENT_KEYS)
        if unknown:
            raise ValueError(f"包含不支持的 Meta 事件键：{', '.join(sorted(unknown))}")
        invalid = {
            item
            for item in value.values()
            if item not in {None, "", "disabled"} and item not in META_STANDARD_EVENTS
        }
        if invalid:
            raise ValueError(f"包含不支持的 Meta 标准事件：{', '.join(sorted(invalid))}")
        return normalized_meta_event_mapping(value)

    @field_validator("subdomain_prefix")
    @classmethod
    def valid_subdomain_prefix(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", normalized):
            raise ValueError("子域名前缀格式不正确")
        return normalized

    @field_validator("locale")
    @classmethod
    def valid_locale(cls, value: str | None) -> str | None:
        if value is None: return None
        normalized = value.replace("_", "-")
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", normalized): raise ValueError("locale 格式不正确")
        return normalized


class PromotionChannelUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    country_code: str | None = Field(default=None, alias="countryCode")
    template_id: str | None = Field(
        default=None,
        alias="templateId",
        validation_alias=AliasChoices("templateId", "templatePublicId"),
    )
    domain_id: str | None = Field(
        default=None,
        alias="domainId",
        validation_alias=AliasChoices("domainId", "domainPublicId"),
    )
    subdomain_prefix: str | None = Field(
        default=None, alias="subdomainPrefix", max_length=63
    )
    slug: str | None = None
    pixel_id: str | None = Field(
        default=None,
        alias="pixelId",
        validation_alias=AliasChoices("pixelId", "pixelPublicId"),
    )
    account_group_id: str | None = Field(
        default=None,
        alias="accountGroupId",
        validation_alias=AliasChoices("accountGroupId", "accountGroupPublicId"),
    )
    protocol_node_id: str | None = Field(
        default=None, alias="protocolNodeId", max_length=20
    )
    protocol_pool_id: str | None = Field(
        default=None, alias="protocolPoolId", max_length=20
    )
    meta_browser_pixel_enabled: bool | None = Field(
        default=None, alias="metaBrowserPixelEnabled"
    )
    meta_capi_enabled: bool | None = Field(
        default=None, alias="metaCapiEnabled"
    )
    meta_event_mapping: dict[str, str | None] | None = Field(
        default=None, alias="metaEventMapping"
    )
    in_app_browser_mode: Literal["allow", "guide_external"] | None = Field(
        default=None, alias="inAppBrowserMode"
    )
    new_account_marketing_enabled: bool | None = Field(
        default=None, alias="newAccountMarketingEnabled"
    )
    locale_mode: Literal["auto", "fixed"] | None = Field(default=None, alias="localeMode")
    locale: str | None = Field(default=None, max_length=16)
    status: Literal["draft", "active", "paused"] | None = None
    launch_at: datetime | None = Field(default=None, alias="launchAt")

    _country = field_validator("country_code")(normalize_country)
    _slug = field_validator("slug")(lambda value: normalize_slug(value) if value else None)
    _protocol_node_id = field_validator("protocol_node_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )
    _protocol_pool_id = field_validator("protocol_pool_id")(
        lambda value: str(parse_snowflake_id(value)) if value else None
    )

    @model_validator(mode="after")
    def one_protocol_route(self):
        if self.protocol_node_id and self.protocol_pool_id:
            raise ValueError("渠道只能绑定协议节点或协议池中的一种")
        return self

    @field_validator("meta_event_mapping")
    @classmethod
    def valid_meta_event_mapping(
        cls, value: dict[str, str | None] | None
    ) -> dict[str, str] | None:
        if value is None:
            return None
        from app.services.meta_conversions import (
            META_EVENT_KEYS,
            META_STANDARD_EVENTS,
            normalized_meta_event_mapping,
        )

        unknown = set(value).difference(META_EVENT_KEYS)
        if unknown:
            raise ValueError(f"包含不支持的 Meta 事件键：{', '.join(sorted(unknown))}")
        invalid = {
            item
            for item in value.values()
            if item not in {None, "", "disabled"} and item not in META_STANDARD_EVENTS
        }
        if invalid:
            raise ValueError(f"包含不支持的 Meta 标准事件：{', '.join(sorted(invalid))}")
        return normalized_meta_event_mapping(value)

    @field_validator("subdomain_prefix")
    @classmethod
    def valid_subdomain_prefix(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", normalized):
            raise ValueError("子域名前缀格式不正确")
        return normalized

    @field_validator("locale")
    @classmethod
    def valid_locale(cls, value: str | None) -> str | None:
        if value is None: return None
        normalized = value.replace("_", "-")
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", normalized): raise ValueError("locale 格式不正确")
        return normalized


class PublicEvent(Model):
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=160)
    event_type: str | None = Field(default=None, alias="eventType", max_length=32)
    occurred_at: datetime | None = Field(default=None, alias="occurredAt")
    channel: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, alias="countryCode")
    metadata: dict = Field(default_factory=dict)
    visitor_id: str | None = Field(default=None, alias="visitorId", min_length=8, max_length=80)

    _country = field_validator("country_code")(normalize_country)
    _metadata = field_validator("metadata")(lambda value: validate_structured_json(value, max_bytes=4096))


FINGERPRINT_COMPONENT_NAMES = {
    "audio",
    "canvas",
    "fonts",
    "hardware",
    "locales",
    "math",
    "plugins",
    "screen",
    "speech",
    "system",
    "timezone",
    "webgl",
}


class PromotionFingerprintComponents(Model):
    audio: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    canvas: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fonts: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    hardware: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    locales: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    math: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plugins: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    screen: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    speech: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    system: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    timezone: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    webgl: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PromotionDeviceFingerprint(Model):
    version: Literal["device-fingerprint/v1"]
    profile: Literal["chromium", "brave", "firefox", "safari", "other"]
    components: PromotionFingerprintComponents
    availability: dict[
        str, Literal["ok", "unavailable", "timeout", "error"]
    ] = Field(default_factory=dict, max_length=16)
    elapsed_ms: int = Field(alias="elapsedMs", ge=0, le=5_000)

    @field_validator("availability")
    @classmethod
    def known_availability_components(
        cls,
        value: dict[str, Literal["ok", "unavailable", "timeout", "error"]],
    ) -> dict[str, Literal["ok", "unavailable", "timeout", "error"]]:
        if not set(value).issubset(FINGERPRINT_COMPONENT_NAMES):
            raise ValueError("设备指纹包含未知组件")
        return value


class PromotionIntegrationEventInput(Model):
    event_type: str = Field(
        alias="eventType",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_.-]{0,63}$",
    )
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=160)
    visitor_id: str = Field(alias="visitorId", min_length=8, max_length=80)
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=2000)
    occurred_at: datetime | None = Field(default=None, alias="occurredAt")
    metadata: dict = Field(default_factory=dict)
    device_fingerprint: PromotionDeviceFingerprint | None = Field(
        default=None, alias="deviceFingerprint"
    )

    _metadata = field_validator("metadata")(
        lambda value: validate_structured_json(value, max_bytes=4096)
    )


class PromotionEventInput(PublicEvent):
    event_type: Literal[
        "page_view", "phone_submit", "visit_end", "inspection_detected"
    ] = Field(alias="eventType")
    phone: str | None = None
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=1000)
    device_fingerprint: PromotionDeviceFingerprint | None = Field(
        default=None, alias="deviceFingerprint"
    )

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)


class PromotionPairingStart(Model):
    phone: str
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=1000)
    visitor_id: str = Field(alias="visitorId", min_length=8, max_length=80)
    device_token: str | None = Field(
        default=None, alias="deviceToken", min_length=40, max_length=4096
    )

    _phone = field_validator("phone")(normalize_phone)


class MetaDomainUnavailableInput(Model):
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=1000)
    dataset_id: str = Field(
        alias="datasetId",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class PromotionSuccessInput(Model):
    promotion_channel_id: str = Field(alias="promotionChannelId", min_length=1, max_length=64)
    event_type: Literal["login_success", "pair_success"] = Field(alias="eventType")
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=160)
    visitor_id: str = Field(alias="visitorId", min_length=8, max_length=80)
    occurred_at: datetime | None = Field(default=None, alias="occurredAt")
    metadata: dict = Field(default_factory=dict)

    _metadata = field_validator("metadata")(
        lambda value: validate_structured_json(value, max_bytes=4096)
    )


class MaterialCreate(StructuredCreate):
    material_type: Literal["text", "contact"] = Field(alias="type")
    text_role: TextMaterialRole | None = Field(default=None, alias="textRole")

    @model_validator(mode="after")
    def validate_material_content(self):
        if self.material_type == "text":
            self.text_role = self.text_role or "body"
            self.content_json = validate_text_material_content(
                self.content_json, self.text_role
            )
        elif self.text_role is not None:
            raise ValueError("只有文本素材可以设置用途")
        return self


class MaterialUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    material_type: Literal["text", "contact"] | None = Field(default=None, alias="type")
    text_role: TextMaterialRole | None = Field(default=None, alias="textRole")
    content_json: dict | None = Field(default=None, alias="contentJson")
    enabled: bool | None = None
    _content = field_validator("content_json")(lambda value: validate_structured_json(value) if value is not None else None)


class HyperlinkTemplateCreate(StructuredCreate):
    material_id: str | None = Field(default=None, alias="materialId")
    promotion_channel_id: str | None = Field(default=None, alias="promotionChannelId")

    _template_content = field_validator("content_json")(validate_hyperlink_template_content)


class HyperlinkTemplateUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content_json: dict | None = Field(default=None, alias="contentJson")
    material_id: str | None = Field(default=None, alias="materialId")
    promotion_channel_id: str | None = Field(default=None, alias="promotionChannelId")
    enabled: bool | None = None
    _content = field_validator("content_json")(
        lambda value: validate_hyperlink_template_content(value) if value is not None else None
    )


class StrategyCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    max_qps: int = Field(default=10, alias="maxQps", ge=1, le=100)
    concurrency: int = Field(default=1, ge=1, le=1000)
    retry_limit: int = Field(default=1, alias="retryLimit", ge=0, le=10)
    retry_backoff_seconds: int = Field(
        default=5, alias="retryBackoffSeconds", ge=0, le=3600
    )
    no_account_action: Literal["wait", "pause"] = Field(
        default="wait", alias="noAccountAction"
    )
    send_jitter_ms: int = Field(default=0, alias="sendJitterMs", ge=0, le=60000)
    account_failure_threshold: int = Field(
        default=3, alias="accountFailureThreshold", ge=1, le=100
    )
    account_cooldown_seconds: int = Field(
        default=300, alias="accountCooldownSeconds", ge=0, le=86400
    )
    rules_json: dict = Field(default_factory=dict, alias="rulesJson")
    enabled: bool = True
    _rules = field_validator("rules_json")(validate_structured_json)


class StrategyUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    max_qps: int | None = Field(default=None, alias="maxQps", ge=1, le=100)
    concurrency: int | None = Field(default=None, ge=1, le=1000)
    retry_limit: int | None = Field(default=None, alias="retryLimit", ge=0, le=10)
    retry_backoff_seconds: int | None = Field(
        default=None, alias="retryBackoffSeconds", ge=0, le=3600
    )
    no_account_action: Literal["wait", "pause"] | None = Field(
        default=None, alias="noAccountAction"
    )
    send_jitter_ms: int | None = Field(
        default=None, alias="sendJitterMs", ge=0, le=60000
    )
    account_failure_threshold: int | None = Field(
        default=None, alias="accountFailureThreshold", ge=1, le=100
    )
    account_cooldown_seconds: int | None = Field(
        default=None, alias="accountCooldownSeconds", ge=0, le=86400
    )
    rules_json: dict | None = Field(default=None, alias="rulesJson")
    enabled: bool | None = None
    _rules = field_validator("rules_json")(lambda value: validate_structured_json(value) if value is not None else None)


class RecipientInput(Model):
    phone: str
    country_code: str | None = Field(default=None, alias="countryCode")
    variables: dict = Field(default_factory=dict)
    _phone = field_validator("phone")(normalize_phone)
    _country = field_validator("country_code")(normalize_country)
    _variables = field_validator("variables")(lambda value: validate_structured_json(value, max_bytes=8192))


class DataPackageCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    recipients: list[RecipientInput] = Field(default_factory=list, max_length=10000)


class DataPackageUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class RecipientsImport(Model):
    recipients: list[RecipientInput] = Field(min_length=1, max_length=10000)


class TaskCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    template_id: str = Field(alias="templateId")
    strategy_id: str = Field(alias="strategyId")
    data_package_id: str = Field(alias="dataPackageId")
    account_group_id: str = Field(alias="accountGroupId", max_length=20)
    channel: str | None = Field(default=None, max_length=80)

    @field_validator("account_group_id")
    @classmethod
    def snowflake_account_group_id(cls, value: str) -> str:
        return str(parse_snowflake_id(value))


class TaskUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    template_id: str | None = Field(default=None, alias="templateId")
    strategy_id: str | None = Field(default=None, alias="strategyId")
    data_package_id: str | None = Field(default=None, alias="dataPackageId")
    account_group_id: str | None = Field(
        default=None, alias="accountGroupId", max_length=20
    )
    channel: str | None = Field(default=None, max_length=80)

    @field_validator("account_group_id")
    @classmethod
    def snowflake_account_group_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(parse_snowflake_id(value))


class AdMetricInput(Model):
    metric_date: date = Field(alias="date")
    promotion_channel_id: str = Field(alias="promotionChannelId")
    spend: float = Field(ge=0, le=1_000_000_000)
    ad_fee_rate: float = Field(
        default=0, alias="adFeeRate", ge=0, le=10_000
    )
    other_cost: float = Field(default=0, alias="otherCost", ge=0, le=1_000_000_000)
    impressions: int = Field(ge=0, le=10_000_000_000)
    clicks: int = Field(ge=0, le=10_000_000_000)


class AdMetricUpdate(Model):
    metric_date: date | None = Field(default=None, alias="date")
    promotion_channel_id: str | None = Field(default=None, alias="promotionChannelId")
    spend: float | None = Field(default=None, ge=0, le=1_000_000_000)
    ad_fee_rate: float | None = Field(
        default=None, alias="adFeeRate", ge=0, le=10_000
    )
    other_cost: float | None = Field(
        default=None, alias="otherCost", ge=0, le=1_000_000_000
    )
    impressions: int | None = Field(default=None, ge=0, le=10_000_000_000)
    clicks: int | None = Field(default=None, ge=0, le=10_000_000_000)


class AdMetricImport(Model):
    rows: list[AdMetricInput] = Field(min_length=1, max_length=10000)
