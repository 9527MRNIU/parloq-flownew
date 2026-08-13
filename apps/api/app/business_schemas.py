from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.validation import normalize_country, normalize_phone, normalize_slug, validate_structured_json


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class PersonalAccountCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")
    enabled: bool = True
    proxy_public_id: str | None = Field(default=None, alias="proxyPublicId")
    group_id: str | None = Field(default=None, alias="groupId", max_length=64)
    source_ref_type: str | None = Field(default=None, alias="sourceRefType", max_length=40)
    source_ref_id: str | None = Field(default=None, alias="sourceRefId", max_length=64)
    protocol_public_id: str | None = Field(
        default=None, alias="protocolId", max_length=64
    )

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)
    _country = field_validator("country_code")(normalize_country)


class PersonalAccountUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = None
    country_code: str | None = Field(default=None, alias="countryCode")
    enabled: bool | None = None
    proxy_public_id: str | None = Field(default=None, alias="proxyPublicId")
    group_id: str | None = Field(default=None, alias="groupId", max_length=64)

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)
    _country = field_validator("country_code")(normalize_country)


class AccountGroupCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class AccountGroupUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ProtocolNodeUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    ingress_enabled: bool | None = Field(default=None, alias="ingressEnabled")
    marketing_enabled: bool | None = Field(default=None, alias="marketingEnabled")


class ProtocolBatchAction(Model):
    protocol_ids: list[str] = Field(
        alias="protocolIds", min_length=1, max_length=1000
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
    device_signals: Literal["off", "standard", "enhanced"] | None = Field(
        default=None, alias="deviceSignals"
    )


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
    template_public_id: str = Field(alias="templatePublicId")
    domain_public_id: str | None = Field(default=None, alias="domainPublicId")
    slug: str
    pixel_public_id: str | None = Field(default=None, alias="pixelPublicId")
    locale_mode: Literal["auto", "fixed"] = Field(default="auto", alias="localeMode")
    locale: str | None = Field(default=None, max_length=16)
    status: Literal["draft", "active", "paused"] = "draft"
    launch_at: datetime | None = Field(default=None, alias="launchAt")

    _country = field_validator("country_code")(normalize_country)
    _slug = field_validator("slug")(normalize_slug)

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
    template_public_id: str | None = Field(default=None, alias="templatePublicId")
    domain_public_id: str | None = Field(default=None, alias="domainPublicId")
    slug: str | None = None
    pixel_public_id: str | None = Field(default=None, alias="pixelPublicId")
    locale_mode: Literal["auto", "fixed"] | None = Field(default=None, alias="localeMode")
    locale: str | None = Field(default=None, max_length=16)
    status: Literal["draft", "active", "paused"] | None = None
    launch_at: datetime | None = Field(default=None, alias="launchAt")

    _country = field_validator("country_code")(normalize_country)
    _slug = field_validator("slug")(lambda value: normalize_slug(value) if value else None)

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


class PromotionEventInput(PublicEvent):
    event_type: Literal[
        "page_view", "phone_submit", "visit_end", "inspection_detected"
    ] = Field(alias="eventType")
    phone: str | None = None
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=1000)

    _phone = field_validator("phone")(lambda value: normalize_phone(value) if value else None)


class PromotionPairingStart(Model):
    phone: str
    session_token: str = Field(alias="sessionToken", min_length=20, max_length=1000)
    visitor_id: str = Field(alias="visitorId", min_length=8, max_length=80)

    _phone = field_validator("phone")(normalize_phone)


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
    material_type: Literal["text", "image", "video", "document", "link"] = Field(alias="type")


class MaterialUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    material_type: Literal["text", "image", "video", "document", "link"] | None = Field(default=None, alias="type")
    content_json: dict | None = Field(default=None, alias="contentJson")
    enabled: bool | None = None
    _content = field_validator("content_json")(lambda value: validate_structured_json(value) if value is not None else None)


class HyperlinkTemplateCreate(StructuredCreate):
    material_id: str | None = Field(default=None, alias="materialId")
    promotion_channel_id: str | None = Field(default=None, alias="promotionChannelId")


class HyperlinkTemplateUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content_json: dict | None = Field(default=None, alias="contentJson")
    material_id: str | None = Field(default=None, alias="materialId")
    promotion_channel_id: str | None = Field(default=None, alias="promotionChannelId")
    enabled: bool | None = None
    _content = field_validator("content_json")(lambda value: validate_structured_json(value) if value is not None else None)


class StrategyCreate(Model):
    name: str = Field(min_length=1, max_length=120)
    max_qps: int = Field(default=10, alias="maxQps", ge=1, le=100)
    concurrency: int = Field(default=1, ge=1, le=1000)
    batch_size: int = Field(default=100, alias="batchSize", ge=1, le=10000)
    retry_limit: int = Field(default=1, alias="retryLimit", ge=0, le=10)
    rules_json: dict = Field(default_factory=dict, alias="rulesJson")
    enabled: bool = True
    _rules = field_validator("rules_json")(validate_structured_json)


class StrategyUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    max_qps: int | None = Field(default=None, alias="maxQps", ge=1, le=100)
    concurrency: int | None = Field(default=None, ge=1, le=1000)
    batch_size: int | None = Field(default=None, alias="batchSize", ge=1, le=10000)
    retry_limit: int | None = Field(default=None, alias="retryLimit", ge=0, le=10)
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
    account_ids: list[str] = Field(alias="accountIds", min_length=1, max_length=1000)
    channel: str | None = Field(default=None, max_length=80)


class TaskUpdate(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    template_id: str | None = Field(default=None, alias="templateId")
    strategy_id: str | None = Field(default=None, alias="strategyId")
    data_package_id: str | None = Field(default=None, alias="dataPackageId")
    account_ids: list[str] | None = Field(default=None, alias="accountIds", min_length=1, max_length=1000)
    channel: str | None = Field(default=None, max_length=80)


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
